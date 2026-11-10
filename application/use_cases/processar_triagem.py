"""
Caso de Uso de Aplicação: ProcessarTriagemUseCase
Orquestra o ciclo de vida completo da triagem clínica:
1. Persistência do documento original recebido em 'recebidos/' no OCI.
2. Execução do grafo condicional de decisão (LangGraph).
3. Emissão de alertas para emergências médicas.
4. Mapeamento para o contrato oficial de saída (TriagemResponseDTO).
5. Persistência do relatório auditável em 'processados/' ou 'auditoria_humana/' no OCI.
"""

import base64
import logging
from typing import Optional, Dict, Any

from domain.ports.llm_port import LLMPort
from domain.ports.storage_port import StoragePort
from domain.ports.notifier_port import NotifierPort
from application.dtos.input_request import TriagemRequestDTO
from application.dtos.output_response import (
    TriagemResponseDTO,
    StatusProcessamentoEnum,
    ClassificacaoDTO,
    NivelPrioridadeEnum,
    DadosExtraidosDTO,
    PacienteDTO,
    MedicoSolicitanteDTO,
    DecisaoRoteamentoDTO,
    NotificacaoGeradaDTO,
    ArmazenamentoOciDTO,
)
from application.workflows.graph import criar_grafo_triagem
from application.use_cases.acompanhar_fluxo import chave_fluxo, novo_registro, registrar_etapa
from application.use_cases.identidade_documento import chave_cadastro, reservar_cadastro, caminho_execucao

logger = logging.getLogger("MediFlowUseCase")


class ProcessarTriagemUseCase:
    """
    Caso de uso primário que implementa o isolamento de regras de aplicação
    e conecta a camada de apresentação aos adaptadores de infraestrutura.
    """

    def __init__(
        self,
        llm: LLMPort,
        storage: StoragePort,
        notifier: NotifierPort,
        bucket_name: str,
    ):
        self.grafo = criar_grafo_triagem(llm)
        self.storage = storage
        self.notifier = notifier
        self.bucket_name = bucket_name

    def _salvar_documento_original(self, request: TriagemRequestDTO, registro: dict) -> Optional[str]:
        """
        Salva o arquivo bruto original (PDF, Imagem ou Texto) no prefixo 'recebidos/' da OCI.
        """
        tipo = request.tipo_arquivo.value.upper()
        extensao = "pdf" if tipo == "PDF" else ("jpg" if tipo == "IMAGEM" else "txt")
        caminho_bruto = f"recebidos/{caminho_execucao(request.documento_id, registro['execucao_id'])}.{extensao}"

        content_type = "application/pdf" if tipo == "PDF" else ("image/jpeg" if tipo == "IMAGEM" else "text/plain; charset=utf-8")

        dados_bytes: bytes = b""
        if request.arquivo_base64:
            try:
                dados_bytes = base64.b64decode(request.arquivo_base64)
            except Exception:
                dados_bytes = request.arquivo_base64.encode("utf-8")
        elif request.documento_texto:
            dados_bytes = request.documento_texto.encode("utf-8")

        if not dados_bytes:
            return None

        registro["caminho_documento_bruto"] = caminho_bruto
        try:
            confirmacao = self.storage.salvar_arquivo(
                bucket_name=self.bucket_name,
                object_name=caminho_bruto,
                data=dados_bytes,
                content_type=content_type,
            )
            return caminho_bruto if confirmacao else None
        except Exception as exc:
            logger.warning(
                "Falha ao persistir documento original %s em OCI Object Storage: %s",
                caminho_bruto,
                exc
            )
            return None

    def _notificar(self, alerta: Dict[str, str]) -> NotificacaoGeradaDTO:
        """Envia uma notificação; a falha é registrada sem interromper a triagem."""
        canal = alerta.get("canal", "Alerta_Plantao_Medico")
        mensagem = alerta.get("mensagem", "")
        try:
            self.notifier.enviar_alerta_urgencia(canal=canal, mensagem=mensagem)
        except Exception as exc:
            logger.warning("Falha ao enviar notificação para %s: %s", canal, exc)
        return NotificacaoGeradaDTO(canal=canal, mensagem=mensagem)

    def executar(self, request: TriagemRequestDTO, *, reprocessamento_de=None, execucao_anterior_id=None) -> TriagemResponseDTO:
        conteudo = request.conteudo_para_extracao()
        registro = novo_registro(request.documento_id)
        if reprocessamento_de is None:
            reservar_cadastro(self.storage, self.bucket_name, registro)
        else:
            registro["reprocessamento_de"] = reprocessamento_de
            registro["execucao_anterior_id"] = execucao_anterior_id
        registro["canal_origem"] = request.canal_origem
        registro["tipo_arquivo"] = request.tipo_arquivo.value
        original_confirmado = False
        try:
            registrar_etapa(self.storage, self.bucket_name, registro, "recebidos")
            if not self._salvar_documento_original(request, registro):
                raise RuntimeError("Não foi possível preservar o documento original. A triagem não foi iniciada.")
            original_confirmado = True
            return self._executar(request, registro, conteudo)
        except Exception:
            try:
                self._tratar_interrupcao(registro, reprocessamento_de is None and not original_confirmado)
            except Exception:
                logger.exception("Falha ao tratar interrupção de %s", request.documento_id)
            raise

    def _tratar_interrupcao(self, registro, pode_cancelar_cadastro):
        if pode_cancelar_cadastro:
            bruto = registro.get("caminho_documento_bruto")
            try:
                sem_original = bruto is None or self.storage.obter_arquivo(self.bucket_name, bruto) is None
            except Exception:
                logger.exception("Falha ao verificar se o original foi salvo")
                sem_original = False
            if sem_original:
                documento_id = registro["documento_id"]
                self.storage.cancelar_cadastro(
                    self.bucket_name, chave_cadastro(documento_id),
                    chave_fluxo(documento_id, registro["execucao_id"]),
                )
                return
        registrar_etapa(self.storage, self.bucket_name, registro, "falha",
                       mensagem="Processamento interrompido. Confira o documento antes de reenviar.")

    def _executar(self, request: TriagemRequestDTO, registro, conteudo) -> TriagemResponseDTO:
        """Executa o grafo e persiste o resultado da triagem."""
        caminho_doc_original = registro["caminho_documento_bruto"]
        registrar_etapa(self.storage, self.bucket_name, registro, "em_analise")

        # 2. Definição do conteúdo para processamento da LLM

        estado_inicial: Dict[str, Any] = {
            "documento_id": request.documento_id,
            "tipo_arquivo": request.tipo_arquivo.value,
            "conteudo": conteudo,
            "canal_origem": request.canal_origem,
        }

        # 3. Execução do grafo condicional de agentes
        try:
            resultado = self.grafo.invoke(estado_inicial)
        except Exception as exc:
            logger.error(
                "Falha ao executar o grafo de decisão para %s: %s",
                request.documento_id,
                exc
            )
            raise RuntimeError(
                f"Erro na execução da triagem pelo grafo de agentes: {str(exc)}"
            ) from exc

        dados_llm = resultado.get("dados_llm") or {}

        # 4. Disparo de alertas: principal primeiro, depois os complementares.
        notificacao_dto: Optional[NotificacaoGeradaDTO] = None
        if resultado.get("notificacao_gerada"):
            notificacao_dto = self._notificar(resultado["notificacao_gerada"])
        adicionais_dto = [self._notificar(n) for n in resultado.get("notificacoes_adicionais") or []]

        # 5. Mapeamento das estruturas clínicas
        prioridade_str = dados_llm.get("nivel_prioridade", "Rotina")
        try:
            prioridade_enum = NivelPrioridadeEnum(prioridade_str)
        except ValueError:
            prioridade_enum = NivelPrioridadeEnum.ROTINA

        classificacao = ClassificacaoDTO(
            tipo_documento=dados_llm.get("tipo_documento", "Documento Clínico Não Identificado"),
            especialidade=dados_llm.get("especialidade", "Clínica Geral"),
            nivel_prioridade=prioridade_enum,
            score_confianca_classificacao=float(dados_llm.get("score_confianca", 0.0)),
        )

        dados_paciente = dados_llm.get("paciente") or {}
        dados_medico = dados_llm.get("medico_solicitante") or {}

        dados_extraidos = DadosExtraidosDTO(
            paciente=PacienteDTO(
                nome=dados_paciente.get("nome"),
                idade=dados_paciente.get("idade"),
            ),
            medico_solicitante=MedicoSolicitanteDTO(
                nome=dados_medico.get("nome"),
                crm=dados_medico.get("crm"),
            ),
            exame_realizado=dados_llm.get("exame_realizado"),
            diagnostico_principal=dados_llm.get("diagnostico_principal"),
            cid_sugerido=dados_llm.get("cid_sugerido"),
            medicamentos=dados_llm.get("medicamentos", []),
        )

        decisao = DecisaoRoteamentoDTO(
            destino_principal=resultado.get("destino_principal", "Fila_Revisao_Humana"),
            requer_auditoria_humana=resultado.get("requer_auditoria_humana", True),
            justificativa_roteamento=resultado.get(
                "justificativa_roteamento",
                "Roteamento efetuado pelo grafo de decisão condicional."
            ),
            notificacao_gerada=notificacao_dto,
            notificacoes_adicionais=adicionais_dto,
        )

        pasta = resultado.get("pasta_oci_sugerida", "auditoria_humana")
        caminho_decisao_oci = f"{pasta}/{caminho_execucao(request.documento_id, registro['execucao_id'])}.json"

        # 6. Instanciação do DTO de resposta já assumindo 'sucesso' para a persistência
        resposta_final = TriagemResponseDTO(
            status=StatusProcessamentoEnum.ERRO if resultado.get("erro_extracao") else StatusProcessamentoEnum.PROCESSADO,
            documento_id=request.documento_id,
            canal_origem=request.canal_origem,
            execucao_id=registro["execucao_id"],
            tipo_arquivo=request.tipo_arquivo.value,
            criado_em=registro["criado_em"],
            reprocessamento_de=registro.get("reprocessamento_de"),
            execucao_anterior_id=registro.get("execucao_anterior_id"),
            erro_extracao=resultado.get("erro_extracao"),
            classificacao=classificacao,
            dados_extraidos=dados_extraidos,
            decisao_roteamento=decisao,
            armazenamento_oci=ArmazenamentoOciDTO(
                bucket=self.bucket_name,
                caminho_objeto=caminho_decisao_oci,
                caminho_documento_bruto=caminho_doc_original,
                status_backup="sucesso" if caminho_doc_original else "falha",
            ),
        )

        # 7. Persistência do relatório JSON no OCI Object Storage com o estado consistente
        try:
            sucesso_salvar = self.storage.salvar_json(
                bucket_name=self.bucket_name,
                object_name=caminho_decisao_oci,
                json_data=resposta_final.model_dump(),  # Grava no OCI com status_backup="sucesso"
            )
            if not sucesso_salvar:
                resposta_final.armazenamento_oci.status_backup = "falha"
        except Exception as exc:
            logger.error(
                "Erro ao persistir decisão de %s no OCI: %s",
                request.documento_id,
                exc
            )
            resposta_final.armazenamento_oci.status_backup = "falha"

        try:
            documento = resposta_final.model_dump(mode="json")
            if resposta_final.armazenamento_oci.status_backup == "falha":
                registrar_etapa(self.storage, self.bucket_name, registro, "falha", documento, "Falha ao armazenar o original ou o resultado da triagem.")
            elif decisao.requer_auditoria_humana:
                registrar_etapa(self.storage, self.bucket_name, registro, "revisao_humana", documento)
            else:
                registrar_etapa(self.storage, self.bucket_name, registro, "processados", documento)
                registrar_etapa(self.storage, self.bucket_name, registro, "encaminhados", documento)
        except Exception:
            resposta_final.acompanhamento_fluxo_confirmado = False
            logger.error("Resultado retornado, mas acompanhamento não confirmado para %s", request.documento_id)
        return resposta_final
