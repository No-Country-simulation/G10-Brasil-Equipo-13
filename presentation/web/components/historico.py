"""Linha do tempo baseada exclusivamente nos eventos persistidos."""
from datetime import datetime, timezone

import requests
import streamlit as st

from presentation.web.api_client import consultar


ETAPAS = {
    "recebidos": "Documento recebido",
    "em_analise": "Análise iniciada",
    "revisao_humana": "Revisão humana solicitada",
    "processados": "Processamento concluído",
    "encaminhados": "Destino registrado",
    "rejeitados": "Documento rejeitado na revisão",
    "falha": "Falha registrada",
}


def horario_evento(valor):
    if not valor:
        return "Horário não registrado"
    try:
        instante = datetime.fromisoformat(valor)
        if instante.tzinfo is None:
            return instante.strftime("%d/%m/%Y %H:%M:%S") + " (fuso não registrado)"
        return instante.astimezone(timezone.utc).strftime("%d/%m/%Y %H:%M:%S UTC")
    except (ValueError, TypeError):
        return "Horário indisponível"


def registro_do_documento(registros, documento):
    if documento.get("registro_id"):
        return next((r for r in registros if r.get("registro_id") == documento["registro_id"]), None)
    return next((r for r in registros if r.get("documento_id") == documento.get("documento_id")
                 and r.get("execucao_id") == documento.get("execucao_id")
                 and (documento.get("execucao_id") or r.get("registro_id") == documento.get("registro_id"))), None)


def exibir_historico(documento):
    with st.container(border=True):
        st.subheader("Linha do tempo do documento", icon=":material/history:")
        st.caption("Eventos da execução deste documento. Destino registrado não comprova recebimento por um sistema externo.")
        try:
            registros = consultar("filas/processamento")
            if not isinstance(registros, list):
                raise ValueError("Resposta inválida")
            registro = registro_do_documento(registros, documento)
        except (requests.RequestException, ValueError):
            st.warning("Não foi possível consultar o histórico. O resultado do documento continua disponível. Tente Atualizar dados.")
            return
        if not registro or not registro.get("eventos"):
            st.info("Histórico de etapas não disponível para esta execução.")
        else:
            for numero, evento in enumerate(registro["eventos"], 1):
                etapa = evento.get("etapa")
                st.markdown(f"**{numero}. {ETAPAS.get(etapa, 'Etapa registrada')}**")
                st.caption(horario_evento(evento.get("em")))
        if registro:
            if registro.get("registro_anterior"):
                st.caption("Registro anterior ao acompanhamento de etapas.")
            if registro.get("registro_reconciliado"):
                etapa = ETAPAS.get(registro.get("etapa"), "Estado atualizado")
                st.info(f"{etapa}: estado confirmado pelo resultado salvo; horário da transição não registrado.")
            if registro.get("mensagem"):
                st.warning(registro["mensagem"])
