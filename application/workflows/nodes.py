from application.workflows.rules import requer_auditoria, validar_formato_crm
from domain.ports.llm_port import LLMPort
from domain.exceptions import FalhaExtracaoIA
from application.workflows.state import WorkflowTriagemState


class TriagemNodes:
    def __init__(self, llm_adapter: LLMPort):
        self.llm_adapter = llm_adapter

    def no_extracao_multimodal(self, state: WorkflowTriagemState) -> WorkflowTriagemState:
        """Invoca o adaptador de IA para classificar e extrair entidades clínicas."""
        try:
            resultado = self.llm_adapter.processar_documento(
                conteudo=state["conteudo"], tipo_arquivo=state["tipo_arquivo"]
            )
        except FalhaExtracaoIA as exc:
            return {
                "dados_llm": {}, "score_confianca": 0.0, "achado_critico": False,
                "erro_extracao": {"codigo": exc.codigo, "mensagem": str(exc)},
            }
        return {
            "dados_llm": resultado,
            "score_confianca": resultado.get("score_confianca", 0.0),
            "achado_critico": resultado.get("achado_critico", False),
            "erro_extracao": None,
        }

    def no_avaliar_urgencia(self, state: WorkflowTriagemState) -> WorkflowTriagemState:
        """Processa casos com achados clínicos críticos de alta gravidade."""
        
        paciente_dict = state["dados_llm"].get("paciente") or {}
        paciente_nome = paciente_dict.get("nome") or "Paciente não identificado"
 
        diagnostico = state["dados_llm"].get("diagnostico_principal") or "Condição Crítica"
        
        pendencia = self.no_encaminhar_auditoria(state) if requer_auditoria(state) else None
        return {
            "requer_auditoria_humana": pendencia is not None,
            "destino_principal": "Fila_Emergencia_Medica",
            "justificativa_roteamento": f"Achado crítico de alta gravidade ({diagnostico}) detectado." + (" " + pendencia["justificativa_roteamento"] if pendencia else ""),
            "notificacao_gerada": {
                "canal": "Alerta_Plantao_Medico",
                "mensagem": f"ALERTA URGENTE: Diagnóstico crítico de {diagnostico} para paciente {paciente_nome}."
            },
            # A pendência também avisa a auditoria, sem substituir o alerta ao plantão.
            "notificacoes_adicionais": [pendencia["notificacao_gerada"]] if pendencia and pendencia.get("notificacao_gerada") else [],
            "caminho_oci_sugerido": pendencia["caminho_oci_sugerido"] if pendencia else f"processados/urgentes/{state['documento_id']}.json"
        }

    def no_rotear_padrao(self, state: WorkflowTriagemState) -> WorkflowTriagemState:
        """Direciona casos de rotina ou prioritários sem inconsistências graves."""
        tipo_doc = state["dados_llm"].get("tipo_documento", "")
        
        # Mapeamento do setor de destino conforme categoria documental
        if "receit" in tipo_doc.lower():
            destino = "Farmacia_Hospitalar"
        elif "guia" in tipo_doc.lower() or "autoriz" in tipo_doc.lower():
            destino = "Auditoria_de_Autorizacoes"
        else:
            destino = "Prontuario_Eletronico_Paciente"

        prioridade = state["dados_llm"].get("nivel_prioridade", "Rotina")

        return {
            "requer_auditoria_humana": False,
            "destino_principal": destino,
            "justificativa_roteamento": f"Documento classificado como {tipo_doc} validado com alta confiabilidade.",
            "notificacao_gerada": None,
            "caminho_oci_sugerido": f"processados/{prioridade.lower()}/{state['documento_id']}.json"
        }


    def no_encaminhar_auditoria(self, state: WorkflowTriagemState) -> WorkflowTriagemState:
        """Roteamento de contingência para Human-in-the-Loop com justificativa analítica."""
        if state.get("erro_extracao"):
            return {
                "requer_auditoria_humana": True,
                "destino_principal": "Fila_Revisao_Humana",
                "justificativa_roteamento": "Extração não realizada: " + state["erro_extracao"]["mensagem"] + " Documento retido para revisão humana.",
                "notificacao_gerada": None,
                "caminho_oci_sugerido": f"auditoria_humana/{state['documento_id']}.json",
            }
        score = state.get("score_confianca", 0.0)
        dados = state.get("dados_llm") or {}
        
        motivos = []
        if score < 0.85:
            motivos.append(f"Score de confiança insuficiente ({score:.2f})")
            
        paciente = dados.get("paciente") or {}
        if not str(paciente.get("nome") or "").strip():
            motivos.append("Ausência de identificação do paciente")
            
        medico = dados.get("medico_solicitante") or {}
        crm = medico.get("crm")
        if not crm:
            motivos.append("Registro CRM ausente ou ilegível")
        elif not validar_formato_crm(crm):
            motivos.append(f"Formato de CRM inconsistente ('{crm}')")

        tipo_doc = str(dados.get("tipo_documento", "")).lower()
        if "receit" in tipo_doc and len(dados.get("medicamentos") or []) == 0:
            motivos.append("Receituário sem posologias/fármacos detectados")

        if not motivos:
            motivos.append("Inconsistência cadastral ou ambiguidade documental")

        justificativa = "Documento retido para auditoria humana: " + "; ".join(motivos) + "."

        return {
            "requer_auditoria_humana": True,
            "destino_principal": "Fila_Revisao_Humana",
            "justificativa_roteamento": justificativa,
            "notificacao_gerada": {
                "canal": "Email_Auditoria",
                "mensagem": f"DOCUMENTO PENDENTE: Documento {state['documento_id']} retido. Motivo: {'; '.join(motivos)}."
            },
            "caminho_oci_sugerido": f"auditoria_humana/{state['documento_id']}.json"
        }
