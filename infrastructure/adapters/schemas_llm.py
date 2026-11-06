from typing import Optional, List, Literal
from pydantic import BaseModel, Field


class PacienteLLMSchema(BaseModel):
    nome: Optional[str] = Field(None, description="Nome completo do paciente identificado")
    idade: Optional[int] = Field(None, ge=0, le=130, description="Idade do paciente em anos")


class MedicoSolicitanteLLMSchema(BaseModel):
    nome: Optional[str] = Field(None, description="Nome do médico solicitante ou emissor")
    crm: Optional[str] = Field(None, description="Registo CRM com estado/UF (ex: 145892-SP)")


class ExtracaoClinicaLLMSchema(BaseModel):
    """Schema estrito para extração de entidades clínicas via LLM Multimodal."""
    tipo_documento: Literal[
        "Receituário Médico",
        "Laudo de Exame Laboratorial",
        "Laudo de Exame de Imagem",
        "Guia de Solicitação de Procedimento",
        "Relatório de Alta/Internação",
        "Autorização Administrativa",
        "Atestado Médico",
    ] = Field(
        ...,
        description="Categoria documental. Selecione exclusivamente uma das sete categorias permitidas."
    )
    especialidade: str = Field(
        ..., 
        description="Especialidade médica (ex: Radiologia / Pneumologia, Cardiologia)"
    )
    nivel_prioridade: Literal["Urgente", "Prioritário", "Rotina"] = Field(
        ..., 
        description="Gravidade clínica: 'Urgente', 'Prioritário' ou 'Rotina'"
    )
    score_confianca: float = Field(
        ..., 
        ge=0.0, 
        le=1.0, 
        description="Grau de certeza da extração e legibilidade do documento (0.0 a 1.0)"
    )
    paciente: PacienteLLMSchema
    medico_solicitante: MedicoSolicitanteLLMSchema
    exame_realizado: Optional[str] = Field(None, description="Nome do exame, procedimento ou consulta")
    diagnostico_principal: Optional[str] = Field(None, description="Diagnóstico principal ou achado clínico crítico")
    cid_sugerido: Optional[str] = Field(None, description="Código CID-10 identificado ou sugerido (ex: I26.9)")
    medicamentos: List[str] = Field(default_factory=list, description="Lista de fármacos e dosagens prescritos")
    achado_critico: bool = Field(
        ..., 
        description="Verdadeiro se existir risco iminente à vida (ex: TEP, Enfarte, AVC, Pneumotórax hipertensivo)"
    )
