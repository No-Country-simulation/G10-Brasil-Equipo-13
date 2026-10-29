"""Kanban consultivo: transições comandadas pelo processamento e pela auditoria."""
from datetime import datetime
import requests
import streamlit as st
from presentation.web import api_client
from presentation.web.components.documentos import chave_documento
from presentation.web.components.layout import cabecalho, indicadores, estado_vazio, nome_destino

ETAPAS = {
    "recebidos": ("Recebidos", "Documentos recebidos pelo serviço."),
    "em_analise": ("Em análise", "Classificação e extração em execução."),
    "revisao_humana": ("Revisão humana", "Aguardam conferência e decisão."),
    "processados": ("Processados", "Triagem concluída, antes do registro de destino."),
    "encaminhados": ("Encaminhados", "Destino registrado pelo sistema."),
}


def horario(valor):
    if not valor:
        return "Horário não registrado"
    return datetime.fromisoformat(valor).strftime("%d/%m/%Y %H:%M:%S UTC")


def cartao(item):
    doc = item.get("documento") or {}
    classificacao = doc.get("classificacao") or {}
    paciente = (doc.get("dados_extraidos", {}).get("paciente") or {}).get("nome")
    decisao = doc.get("decisao_roteamento") or {}
    with st.container(border=True):
        st.markdown("**" + item["documento_id"] + "**")
        st.write(paciente or "Paciente ainda não identificado")
        st.caption(classificacao.get("tipo_documento") or "Categoria ainda não identificada")
        if doc.get("erro_extracao"):
            st.badge("Extração não realizada", color="orange")
        elif classificacao.get("nivel_prioridade"):
            prioridade = classificacao["nivel_prioridade"]
            st.badge(prioridade, color="red" if prioridade == "Urgente" else "orange" if prioridade == "Prioritário" else "green")
        if decisao.get("destino_principal"):
            st.caption("Destino: " + nome_destino(decisao["destino_principal"]))
        st.caption(horario(item.get("atualizado_em")))
        if item.get("registro_anterior"):
            st.caption("Registro anterior ao acompanhamento de etapas.")
        if item.get("registro_reconciliado"):
            st.caption("Estado confirmado pelo resultado salvo; horário da etapa não registrado.")
        if item.get("mensagem"):
            st.warning(item["mensagem"])
        chave = item.get("registro_id") or item["documento_id"] + "_" + str(item.get("execucao_id"))
        if item["etapa"] == "revisao_humana":
            if st.button("Abrir revisão", key="revisar_" + chave, icon=":material/fact_check:", width="stretch"):
                st.session_state.documento_em_revisao = chave_documento(doc)
                st.switch_page("app_pages/auditoria.py")
        elif item["etapa"] == "falha" and item.get("caminho_documento_bruto") and item.get("registro_id"):
            with st.form("reprocessar_falha_" + chave):
                canal = st.selectbox("Origem do reprocessamento", ["Pronto_Socorro", "Ambulatorio", "Recepcao"])
                reprocessar = st.form_submit_button("Reprocessar original")
            if reprocessar:
                try:
                    resultado = api_client.enviar("reprocessar", {"documento_id": item["documento_id"], "origem_oci_path": item["registro_id"], "canal_origem": canal})
                    st.session_state.documento_em_consulta = resultado["armazenamento_oci"]["caminho_objeto"]
                    st.switch_page("app_pages/documentos.py")
                except (requests.RequestException, ValueError):
                    st.error("Não foi possível confirmar o reprocessamento. Consulte as execuções antes de tentar novamente.")
        elif doc.get("armazenamento_oci", {}).get("caminho_objeto"):
            if st.button("Abrir documento", key="consultar_" + chave, icon=":material/description:", width="stretch"):
                st.session_state.documento_em_consulta = chave_documento(doc)
                st.switch_page("app_pages/documentos.py")
        with st.expander("Etapas registradas", icon=":material/history:"):
            if not item.get("eventos"):
                st.caption("Sem eventos históricos registrados.")
            for evento in item.get("eventos", []):
                titulo = ETAPAS.get(evento["etapa"], (evento["etapa"].capitalize(), ""))[0]
                st.caption(titulo + " · " + horario(evento["em"]))


cabecalho("Filas de processamento", "Acompanhe os documentos em cada etapa do fluxo e abra as pendências para revisão.")
st.caption("Atualização automática a cada 5 segundos enquanto esta página estiver aberta. A movimentação segue as regras do processamento.")


@st.fragment(run_every="5s")
def quadro():
    try:
        registros = api_client.consultar("filas/processamento")
    except (requests.RequestException, ValueError):
        st.error("Não foi possível consultar as filas de processamento. Atualize os dados após verificar a API.")
        return
    indicadores([
        ("Documentos no fluxo", len(registros)),
        ("Em análise", sum(r["etapa"] == "em_analise" for r in registros)),
        ("Em revisão", sum(r["etapa"] == "revisao_humana" for r in registros)),
        ("Classificados urgentes", sum(not (r.get("documento") or {}).get("erro_extracao") and (r.get("documento") or {}).get("classificacao", {}).get("nivel_prioridade") == "Urgente" for r in registros)),
    ])
    with st.container(border=True):
        esquerda, direita = st.columns(2)
        with esquerda:
            busca = st.text_input("Buscar documento ou paciente", key="filas_busca", placeholder="ID ou nome do paciente")
            prioridade = st.selectbox("Prioridade", ["Todas", "Urgente", "Prioritário", "Rotina"], key="filas_prioridade")
        with direita:
            tipos = sorted({(r.get("documento") or {}).get("classificacao", {}).get("tipo_documento") or "Não identificado" for r in registros})
            tipo = st.selectbox("Categoria", ["Todas"] + tipos, key="filas_categoria")
            destinos = sorted({(r.get("documento") or {}).get("decisao_roteamento", {}).get("destino_principal") for r in registros} - {None, ""})
            destino = st.selectbox("Destino", ["Todos"] + destinos, format_func=nome_destino, key="filas_destino")
    filtrados = []
    for item in registros:
        doc = item.get("documento") or {}
        classe = doc.get("classificacao") or {}
        paciente = (doc.get("dados_extraidos", {}).get("paciente") or {}).get("nome") or ""
        if busca.casefold() not in (item["documento_id"] + " " + paciente).casefold():
            continue
        if prioridade != "Todas" and (doc.get("erro_extracao") or classe.get("nivel_prioridade") != prioridade):
            continue
        if tipo != "Todas" and (classe.get("tipo_documento") or "Não identificado") != tipo:
            continue
        if destino != "Todos" and doc.get("decisao_roteamento", {}).get("destino_principal") != destino:
            continue
        filtrados.append(item)
    st.caption("Encaminhado significa destino registrado; não confirma recebimento pelo setor nem atendimento. Etapas rápidas podem aparecer apenas no histórico do cartão. Deslize o quadro para ver as cinco colunas.")
    if not registros:
        estado_vazio("Nenhum documento no fluxo", "Envie um documento para iniciar o acompanhamento.", nova_triagem=True)
    elif not filtrados:
        estado_vazio("Nenhum documento encontrado", "Ajuste os filtros para consultar o quadro.", ":material/search_off:")
    with st.container(horizontal=True, wrap=False):
        for etapa, (titulo, descricao) in ETAPAS.items():
            itens = [r for r in filtrados if r["etapa"] == etapa]
            with st.container(border=True, width=280):
                st.subheader(titulo)
                st.badge(str(len(itens)), color="gray")
                st.caption(descricao)
                for item in itens:
                    cartao(item)
                if not itens:
                    st.caption("Nenhum documento nesta etapa.")
    excecoes = [r for r in filtrados if r["etapa"] not in ETAPAS]
    if excecoes:
        with st.expander(f"Falhas e rejeitados ({len(excecoes)})", expanded=True):
            for item in excecoes:
                st.badge("Rejeitado" if item["etapa"] == "rejeitados" else "Falha no processamento", color="red")
                cartao(item)


quadro()
