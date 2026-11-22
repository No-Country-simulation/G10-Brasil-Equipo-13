"""
Adaptador de Infraestrutura: OpenAI LLM Adapter (GPT-4o)
Implementa a porta LLMPort como alternativa/fallback resiliente ao Google Gemini[cite: 8, 23].
Suporta Structured Outputs estritos via client.beta.chat.completions.parse[cite: 23, 24].
"""

import base64
import binascii
import logging
from typing import Any, Dict, List
from openai import OpenAI

from domain.ports.llm_port import LLMPort
from domain.exceptions import FalhaExtracaoIA
from infrastructure.adapters.schemas_llm import ExtracaoClinicaLLMSchema

logger = logging.getLogger("MediFlowOpenAIAdapter")


class OpenAILLMAdapter(LLMPort):
    """
    Adaptador concreto para integração com modelos da OpenAI (ex.: gpt-4o)[cite: 8, 23].
    Garante conformidade com o schema Pydantic ExtracaoClinicaLLMSchema[cite: 23, 24].
    """

    def __init__(self, api_key: str, model_name: str = "gpt-4o"):
        self.client = OpenAI(api_key=api_key)
        self.model_name = model_name

    def _obter_system_prompt(self) -> str:
        return (
            "Você é um assistente clínico de triagem de alta precisão do sistema MediFlow. "
            "Sua responsabilidade é analisar documentos médicos (imagens digitalizadas, laudos ou texto), "
            "classificar sua categoria e especialidade, extrair entidades clínicas com rigor absoluto e "
            "determinar o nível de gravidade e necessidade de intervenção imediata. "
            "Regras mandatórias:\n"
            "1. Se o documento for ilegível, incompleto, contiver rasuras ou faltar identificação primária, "
            "atribua score_confianca baixo (< 0.85)[cite: 23].\n"
            "2. Se detectar risco de morte iminente (ex.: TEP agudo, AVC, IAM, choque), "
            "defina achado_critico=True e nivel_prioridade='Urgente'[cite: 23].\n"
            "3. Retorne rigorosamente o payload de acordo com a estrutura JSON solicitada."
        )

    def _preparar_mensagens(self, conteudo: Any, tipo_arquivo: str) -> List[Dict[str, Any]]:
        """
        Estrutura a carga de mensagens de forma segura conforme o tipo de entrada[cite: 23].
        - Imagens: enviadas via data URL (JPEG/PNG)[cite: 23].
        - PDFs e Textos: enviados como texto descritivo puro, evitando erros 400 da API da OpenAI.
        """
        tipo = (tipo_arquivo or "TEXTO").strip().upper()
        conteudo_usuario: List[Dict[str, Any]] = []

        if tipo == "IMAGEM":
            b64_string = ""
            if isinstance(conteudo, (bytes, bytearray)):
                b64_string = base64.b64encode(conteudo).decode("utf-8")
            elif isinstance(conteudo, str):
                try:
                    # Valida se a string já é um Base64 íntegro
                    base64.b64decode(conteudo, validate=True)
                    b64_string = conteudo
                except (binascii.Error, ValueError):
                    logger.warning("Conteúdo marcado como IMAGEM não é um Base64 válido. Tratando como texto.")
                    b64_string = ""

            if b64_string:
                data_url = f"data:image/jpeg;base64,{b64_string}"
                conteudo_usuario.append({
                    "type": "text",
                    "text": "Analise o documento médico anexo e extraia rigorosamente todas as entidades clínicas estruturadas[cite: 23]."
                })
                conteudo_usuario.append({
                    "type": "image_url",
                    "image_url": {
                        "url": data_url,
                        "detail": "high"
                    }
                })
                return [{"role": "user", "content": conteudo_usuario}]

        # Para PDFs, JSONs ou Textos planos, envia como bloco textual seguro
        texto_limpo = conteudo.decode("utf-8", errors="ignore") if isinstance(conteudo, (bytes, bytearray)) else str(conteudo)
        conteudo_usuario.append({
            "type": "text",
            "text": f"Analise o seguinte registro clínico e extraia as entidades estruturadas[cite: 23]:\n\n{texto_limpo}"
        })

        return [{"role": "user", "content": conteudo_usuario}]

    def processar_documento(self, conteudo: Any, tipo_arquivo: str) -> Dict[str, Any]:
        """
        Ingere o conteúdo clínico e devolve o dicionário estruturado compatível com o domínio[cite: 23].
        """
        mensagens = [
            {"role": "system", "content": self._obter_system_prompt()}
        ]
        mensagens.extend(self._preparar_mensagens(conteudo, tipo_arquivo))

        try:
            # Chamada com Structured Outputs via Pydantic Schema da OpenAI[cite: 23, 24]
            response = self.client.beta.chat.completions.parse(
                model=self.model_name,
                messages=mensagens,
                response_format=ExtracaoClinicaLLMSchema,
                temperature=0.1
            )

            resultado_estruturado: ExtracaoClinicaLLMSchema = response.choices[0].message.parsed
            if resultado_estruturado is None:
                raise ValueError("A resposta estruturada do modelo OpenAI retornou vazia.")

            return resultado_estruturado.model_dump()

        except Exception as exc:
            logger.error("Falha na chamada ao modelo OpenAI (%s): %s", self.model_name, exc)
            raise FalhaExtracaoIA(
                "resposta_invalida", "Não foi possível obter uma classificação válida do documento."
            ) from exc
