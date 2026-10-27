from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class StatusProcessamentoEnum(str, Enum):
    PROCESSADO = "processado"
    EM_ANALISE = "em_analise"
    ERRO = "erro"


class NivelPrioridadeEnum(str, Enum):
    ROTINA = "Rotina"
    PRIORITARIO = "Prioritário"
    URGENTE = "Urgente"


class ClassificacaoDTO(BaseModel):
    tipo_documento: str = Field(
        ..., 
        description="Categoria identificada do documento",
        examples=["Laudo de Exame de Imagem", "Receituário Médico", "Atestado Médico"]
    )
    especialidade: str = Field(
        ..., 
        description="Especialidade médica associada",
        examples=["Radiologia / Pneumologia"]
    )
    nivel_prioridade: NivelPrioridadeEnum = Field(
        ..., 
        description="Classificação de gravidade e prioridade do caso"
    )
    score_confianca_classificacao: float = Field(
        ..., 
        ge=0.0, 
        le=1.0, 
        description="Confiança do modelo na classificação (0.00 a 1.00)"
    )


class PacienteDTO(BaseModel):
    nome: Optional[str] = Field(None, description="Nome completo do paciente")
    idade: Optional[int] = Field(None, ge=0, le=130, description="Idade em anos")


class MedicoSolicitanteDTO(BaseModel):
    nome: Optional[str] = Field(None, description="Nome do médico solicitante")
    crm: Optional[str] = Field(None, description="Número de registro CRM com UF", examples=["145892-SP"])


class DadosExtraidosDTO(BaseModel):
    paciente: PacienteDTO
    medico_solicitante: MedicoSolicitanteDTO
    exame_realizado: Optional[str] = Field(None, description="Nome do procedimento ou exame")
    diagnostico_principal: Optional[str] = Field(None, description="Hipótese diagnóstica ou achado clínico principal")
    cid_sugerido: Optional[str] = Field(None, description="Código de CID-10 identificado", examples=["I26.9"])
    medicamentos: Optional[list[str]] = Field(default_factory=list, description="Lista de fármacos e posologias")


class NotificacaoGeradaDTO(BaseModel):
    canal: str = Field(..., examples=["Alerta_Plantao_Medico", "Email_Auditoria"])
    mensagem: str = Field(..., description="Mensagem de alerta gerada para a equipe de destino")


class DecisaoRoteamentoDTO(BaseModel):
    destino_principal: str = Field(
        ..., 
        examples=["Fila_Emergencia_Medica", "Auditoria_de_Autorizacoes", "Farmacia_Hospitalar"]
    )
    requer_auditoria_humana: bool = Field(
        ..., 
        description="Sinalizador de contingência caso haja ambiguidade ou baixa confiança"
    )
    justificativa_roteamento: str = Field(..., description="Motivo clínico ou administrativo da decisão")
    notificacao_gerada: Optional[NotificacaoGeradaDTO] = None
    notificacoes_adicionais: list[NotificacaoGeradaDTO] = Field(
        default_factory=list,
        description="Notificações complementares, como o e-mail de auditoria de um caso urgente com pendências",
    )


class ArmazenamentoOciDTO(BaseModel):
    bucket: str = Field(
        ..., 
        description="Nome do bucket no OCI Object Storage",
        examples=["mediflow-documentos-clinicos"]
    )
    caminho_objeto: str = Field(
        ..., 
        description="Caminho do relatório JSON da decisão/triagem",
        examples=["processados/urgentes/DOC-CLIN-2026-8942.json", "auditoria_humana/DOC-CLIN-2026-8942.json"]
    )
    caminho_documento_bruto: Optional[str] = Field(
        default=None,
        description="Caminho do documento original persistido sob o prefixo /recebidos/",
        examples=["recebidos/DOC-CLIN-2026-8942.pdf", "recebidos/DOC-CLIN-2026-8942.txt"]
    )
    status_backup: str = Field(
        ..., 
        description="Status da persistência na nuvem OCI",
        examples=["sucesso", "falha"]
    )


class ErroExtracaoDTO(BaseModel):
    codigo: str
    mensagem: str


class TriagemResponseDTO(BaseModel):
    """Contrato final e padronizado retornado pela API e exportado para o OCI."""
    status: StatusProcessamentoEnum
    documento_id: str
    canal_origem: Optional[str] = Field(
        default=None,
        description="Canal de origem informado no recebimento; ausente em registros antigos",
    )
    execucao_id: Optional[str] = None
    acompanhamento_fluxo_confirmado: bool = True
    erro_extracao: Optional[ErroExtracaoDTO] = None
    classificacao: ClassificacaoDTO
    dados_extraidos: DadosExtraidosDTO
    decisao_roteamento: DecisaoRoteamentoDTO
    armazenamento_oci: ArmazenamentoOciDTO
