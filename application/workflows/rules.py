"""Validações administrativas independentes da criticidade clínica."""
import re
from application.workflows.state import WorkflowTriagemState


def validar_formato_crm(crm: str) -> bool:
    """
    Valida se o CRM possui dígitos seguidos de hífen e UF brasileira válida (ex: '145892-SP' ou '145892/SP').
    Permite tolerância a variações sem hífen se contiver números e estado válido.
    """
    if not crm or not isinstance(crm, str):
        return False

    crm_limpo = crm.strip().upper()
    # Padrão: 4 a 8 dígitos numéricos, separador opcional (- ou /) e sigla da UF (2 letras)
    padrao = re.compile(r"^(\d{4,8})[-/]?([A-Z]{2})$")

    correspondencia = padrao.fullmatch(crm_limpo)
    if not correspondencia:
        return False

    ufs_validas = {
        "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
    }

    return correspondencia.group(2) in ufs_validas


def requer_auditoria(state: WorkflowTriagemState) -> bool:
    score = state.get("score_confianca", 0.0)
    dados = state.get("dados_llm") or {}

    # 1. Validação de Entidades Mandatórias
    paciente = dados.get("paciente") or {}
    paciente_valido = bool(paciente.get("nome") and str(paciente.get("nome")).strip())

    medico = dados.get("medico_solicitante") or {}
    crm_valor = medico.get("crm")
    crm_valido = validar_formato_crm(crm_valor)

    # 2. Avaliação de Potenciais Conflitos Clínicos
    tipo_doc = str(dados.get("tipo_documento", "")).lower()
    medicamentos = dados.get("medicamentos") or []
    exame = dados.get("exame_realizado")
    diagnostico = dados.get("diagnostico_principal")

    houve_conflito = False

    # Conflito A: Receituário sem nenhum fármaco ou posologia extraída
    if "receit" in tipo_doc and len(medicamentos) == 0:
        houve_conflito = True

    # Conflito B: Laudo de exame sem nome de exame e sem diagnóstico clínico
    if "laudo" in tipo_doc and not exame and not diagnostico:
        houve_conflito = True

    return bool(state.get("erro_extracao") or score < 0.85 or not paciente_valido or not crm_valido or houve_conflito)
