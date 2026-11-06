"""
Adaptador de Infraestrutura: Gemini LLM Adapter
Implementa a porta LLMPort utilizando o SDK oficial Google GenAI.
Suporta inferência multimodal (PDF, imagens, texto plano) e Structured Outputs estritos.
"""

import html
import base64
import binascii
import logging
import random
import time
from typing import Any, Dict, List

from google import genai
from google.genai import types
import httpx
from pydantic import BaseModel, ValidationError

from domain.ports.llm_port import LLMPort
from domain.exceptions import FalhaExtracaoIA
from infrastructure.adapters.schemas_llm import ExtracaoClinicaLLMSchema

logger = logging.getLogger("MediFlowGeminiAdapter")


class GeminiLLMAdapter(LLMPort):
    """
    Adaptador concreto para integração com os modelos multimodais da família Google Gemini.
    Implementa a extração padronizada via schema Pydantic (ExtracaoClinicaLLMSchema).
    """

    def __init__(self, api_key: str, model_name: str = "gemini-3.5-flash",
                 timeout_ms: int = 20000, max_attempts: int = 3):
        # Uma única política de repetição: o SDK não multiplica as tentativas.
        self.client = genai.Client(api_key=api_key, http_options=types.HttpOptions(
            timeout=timeout_ms, retry_options=types.HttpRetryOptions(attempts=1),
        ))
        self.model_name = model_name
        self.max_attempts = max(1, min(max_attempts, 3))

    def _obter_system_instruction(self) -> str:
        return (
            "És um assistente clínico de triagem médica de alta precisão do sistema MediFlow. "
            "A tua função é analisar documentos médicos (PDFs digitais/digitalizados, fotos de receitas, "
            "laudos de exames ou texto bruto), classificar a sua categoria documental e extrair dados vitais. "
            "Classifica o documento exclusivamente numa das sete categorias: "
            "Receituário Médico; Laudo de Exame Laboratorial; Laudo de Exame de Imagem; "
            "Guia de Solicitação de Procedimento; Relatório de Alta/Internação; "
            "Autorização Administrativa; Atestado Médico.\n"
            "Distingue Guia de Solicitação de Procedimento, que solicita a realização de "
            "um procedimento, de Autorização Administrativa, que registra a autorização, "
            "negativa ou situação administrativa de uma solicitação. "
            "Não utilizes 'Guia TISS' como categoria documental.\n"
            "Regras mandatórias:\n"
            "1. Atribui score_confianca baixo (< 0.85) se houver rasuras, letras ilegíveis, imagens borradas "
            "ou falta do nome do paciente e CRM.\n"
            "2. Avalia a urgência considerando o estado clínico atual e o contexto temporal. "
            "Define achado_critico=True e nivel_prioridade='Urgente' quando houver evidências "
            "de condição crítica ativa ou risco iminente à vida (ex.: TEP agudo, AVC, enfarte, choque). "
            "Eventos graves históricos, já tratados ou resolvidos, especialmente em relatórios de alta, "
            "não devem isoladamente determinar urgência ou achado_critico=True. "
            "Considera sinais atuais de agravamento e não presume que toda alta hospitalar seja rotina.\n"
            "3. Extrai diagnósticos e códigos CID-10 somente quando estiverem explicitamente "
            "documentados. Não inventes diagnósticos nem atribuas códigos CID por inferência "
            "clínica. Quando a informação estiver ausente, ilegível ou não informada, utiliza "
            "null no campo correspondente. Não confundas histórico clínico com diagnóstico "
            "principal documentado.\n"
            "4. Garante conformidade estrita com o schema JSON configurado."
        )

    def _preparar_partes_multimodais(self, conteudo: Any, tipo_arquivo: str) -> List[Any]:
        """
        Processa com segurança o conteúdo recebido (bytes, string base64 ou texto puro)
        e constrói as partes compatíveis com a API do Gemini.
        """
        tipo = (tipo_arquivo or "TEXTO").strip().upper()
        partes: List[Any] = []

        if tipo in ["PDF", "IMAGEM"]:
            bytes_conteudo: bytes = b""

            # Tratamento defensivo de conversão binária / base64
            if isinstance(conteudo, (bytes, bytearray)):
                bytes_conteudo = bytes(conteudo)
            elif isinstance(conteudo, str):
                try:
                    bytes_conteudo = base64.b64decode(conteudo, validate=True)
                except (binascii.Error, ValueError):
                    logger.warning(
                        "Conteúdo marcado como %s não é um Base64 válido. Tratando como texto plano.",
                        tipo
                    )
                    bytes_conteudo = b""

            if bytes_conteudo:
                mime_type = "application/pdf" if tipo == "PDF" else (
                    "image/png" if bytes_conteudo.startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg"
                )
                partes.append(
                    types.Part.from_bytes(
                        data=bytes_conteudo,
                        mime_type=mime_type,
                    )
                )
                partes.append(
                    "Analisa minuciosamente o documento médico anexo e extrai rigorosamente todas as entidades clínicas."
                )
                return partes

        # Fallback para processamento textual direto
        texto_limpo = conteudo if isinstance(conteudo, str) else str(conteudo)
        partes.append(f"Analisa o seguinte registro clínico e extrai as entidades estruturadas:\n\n{texto_limpo}")
        return partes

    def processar_documento(self, conteudo: Any, tipo_arquivo: str) -> Dict[str, Any]:
        """
        Ingere o documento clínico e retorna o dicionário serializado compatível com o domínio.
        """
        partes = self._preparar_partes_multimodais(conteudo, tipo_arquivo)

        config = types.GenerateContentConfig(
            system_instruction=self._obter_system_instruction(),
            response_mime_type="application/json",
            response_schema=ExtracaoClinicaLLMSchema,
        )

        for tentativa in range(self.max_attempts):
            try:
                response = self.client.models.generate_content(
                    model=self.model_name, contents=partes, config=config,
                )
                parsed = response.parsed
                if isinstance(parsed, BaseModel):
                    parsed = parsed.model_dump()
                if parsed is None:
                    raise ValueError("Resposta estruturada ausente.")
                dados = ExtracaoClinicaLLMSchema.model_validate(
                    parsed, strict=True
                ).model_dump()

                def normalizar_html(valor):
                    if isinstance(valor, str):
                        return html.unescape(valor)
                    if isinstance(valor, list):
                        return [normalizar_html(item) for item in valor]
                    if isinstance(valor, dict):
                        return {chave: normalizar_html(item) for chave, item in valor.items()}
                    return valor

                return normalizar_html(dados)
            except Exception as exc:
                codigo_http = getattr(exc, "code", None)
                temporaria = codigo_http in (408, 429, 500, 502, 503, 504) or isinstance(
                    exc, (httpx.TransportError, TimeoutError, ConnectionError)
                )
                if temporaria and tentativa + 1 < self.max_attempts:
                    time.sleep(2 ** tentativa + random.uniform(0, 0.25))
                    continue
                if isinstance(exc, (ValidationError, ValueError)):
                    codigo, mensagem = "resposta_invalida", "A IA não retornou uma extração estruturada válida."
                elif codigo_http in (401, 403):
                    codigo, mensagem = "acesso_negado", "Credencial ou permissão de acesso à IA recusada."
                elif codigo_http == 400:
                    codigo, mensagem = "requisicao_invalida", "A IA recusou a requisição. Confira a chave, o modelo e o formato do documento."
                elif codigo_http == 404:
                    codigo, mensagem = "modelo_indisponivel", "Modelo indisponível para esta conta. Confira GEMINI_MODEL_NAME."
                elif codigo_http == 429:
                    codigo, mensagem = "limite_uso", "Limite de uso ou cota da IA atingido."
                elif temporaria:
                    codigo, mensagem = "servico_indisponivel", "Não foi possível acessar a IA após as tentativas limitadas."
                else:
                    codigo, mensagem = "falha_ia", "A extração pela IA não pôde ser concluída."
                # Não registrar mensagens brutas do provedor: podem conter dados sensíveis.
                logger.warning("Extração Gemini falhou: codigo=%s; tipo=%s", codigo, type(exc).__name__)
                raise FalhaExtracaoIA(codigo, mensagem) from exc
