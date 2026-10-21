from typing import TypedDict, Optional, Dict, Any, List


class WorkflowTriagemState(TypedDict, total=False):
    # Entradas
    documento_id: str
    tipo_arquivo: str
    conteudo: Any
    canal_origem: str

    # Processamento LLM / Multimodal
    dados_llm: Optional[Dict[str, Any]]
    score_confianca: float
    achado_critico: bool
    erro_extracao: Optional[Dict[str, str]]

    # Decisão de Roteamento
    requer_auditoria_humana: bool
    destino_principal: str
    justificativa_roteamento: str
    notificacao_gerada: Optional[Dict[str, str]]
    notificacoes_adicionais: List[Dict[str, str]]
    caminho_oci_sugerido: str
