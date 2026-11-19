"""Catálogo documental com filtros e conferência dos registros persistidos."""
import requests
import streamlit as st
from presentation.web.api_client import consultar, enviar
from presentation.web.components.resultado import exibir_resultado
from presentation.web.components.historico import exibir_historico
from presentation.web.components.documentos import linhas_documentos, estado_documento, chave_documento, rotulo_documento
from presentation.web.components.layout import cabecalho, indicadores, estado_vazio, nome_destino

cabecalho("Documentos clínicos", "Organize e acompanhe os documentos, suas prioridades e os destinos de encaminhamento.")
with st.container(horizontal=True):
    st.page_link("app_pages/nova_triagem.py", label="Nova triagem", icon=":material/add_circle:")
    st.page_link("app_pages/auditoria.py", label="Revisão humana", icon=":material/fact_check:")
try:
    documentos = consultar("historico")
except (requests.RequestException, ValueError):
    st.error("Não foi possível consultar o histórico. Não há dados confirmados para exibir.")
    st.stop()

indicadores([
    ("Documentos armazenados", len(documentos)),
    ("Classificados urgentes", sum(not d.get("erro_extracao") and d.get("classificacao", {}).get("nivel_prioridade") == "Urgente" for d in documentos)),
    ("Aguardando revisão", sum(bool(d.get("decisao_roteamento", {}).get("requer_auditoria_humana")) for d in documentos)),
])
if not documentos:
    estado_vazio("Nenhum documento armazenado", "Envie um documento para iniciar o fluxo de triagem.", nova_triagem=True)
    st.stop()

with st.container(border=True):
    st.subheader("Pesquisar documentos", icon=":material/search:")
    esquerda, direita = st.columns(2)
    with esquerda:
        busca = st.text_input("Buscar por ID ou paciente", placeholder="Digite o identificador ou nome")
        estado = st.selectbox("Estado", ["Todos"] + sorted({estado_documento(d) for d in documentos}))
        destino = st.selectbox("Destino", ["Todos"] + sorted({d.get("decisao_roteamento", {}).get("destino_principal", "Não informado") for d in documentos}), format_func=nome_destino)
    with direita:
        tipo = st.selectbox("Tipo de documento", ["Todos"] + sorted({d.get("classificacao", {}).get("tipo_documento") or "Não identificado" for d in documentos}))
        prioridade = st.selectbox("Prioridade", ["Todas", "Urgente", "Prioritário", "Rotina", "Não avaliada"])
        revisao = st.selectbox("Necessidade de revisão", ["Todos", "Exige revisão", "Sem revisão pendente"])

filtrados = []
for doc in documentos:
    linha = linhas_documentos([doc])[0]
    exige_revisao = bool(doc.get("decisao_roteamento", {}).get("requer_auditoria_humana"))
    if busca.casefold() not in (linha["Documento"] + " " + linha["Paciente"]).casefold():
        continue
    if estado != "Todos" and linha["Estado"] != estado:
        continue
    if tipo != "Todos" and linha["Tipo"] != tipo:
        continue
    if prioridade != "Todas" and linha["Prioridade"] != prioridade:
        continue
    if destino != "Todos" and doc.get("decisao_roteamento", {}).get("destino_principal", "Não informado") != destino:
        continue
    if revisao == "Exige revisão" and not exige_revisao or revisao == "Sem revisão pendente" and exige_revisao:
        continue
    filtrados.append(doc)

if not filtrados:
    estado_vazio("Nenhum documento encontrado", "Ajuste os filtros para consultar outros registros.", ":material/search_off:")
else:
    with st.container(border=True):
        st.subheader("Registros documentais", icon=":material/description:")
        st.caption(f"{len(filtrados)} de {len(documentos)} documento(s). Estado atual dos registros; não representa um log de eventos ou confirmação de atendimento.")
        st.dataframe(linhas_documentos(filtrados), hide_index=True, alt="Documentos filtrados com seus estados e encaminhamentos")
    with st.container(border=True):
        st.subheader("Conferência do documento", icon=":material/visibility:")
        preferido = st.session_state.pop("documento_em_consulta", None)
        registros = {chave_documento(doc): doc for doc in filtrados}
        rotulos = {chave: rotulo_documento(doc) for chave, doc in registros.items()}
        ids = list(registros)
        preferido = next((chave_documento(d) for d in filtrados if chave_documento(d) == preferido or d["documento_id"] == preferido), preferido)
        if preferido in ids:
            st.session_state.consulta_documento_id = preferido
        elif preferido:
            st.info("O documento selecionado não está nestes resultados. Ajuste os filtros.")
        if st.session_state.get("consulta_documento_id") not in ids:
            st.session_state.consulta_documento_id = ids[0]
        selecionado = st.selectbox("Abrir detalhes do documento", ids, key="consulta_documento_id", format_func=rotulos.get)
        documento = registros[selecionado]
        exibir_resultado(documento)
        exibir_historico(documento)
        st.caption(rotulo_documento(documento))
        with st.form("reprocessar_" + selecionado):
            st.write("Reprocessar o original desta execução preservando os registros anteriores.")
            canal = st.selectbox("Origem do reprocessamento", ["Pronto_Socorro", "Ambulatorio", "Recepcao"])
            reprocessar = st.form_submit_button("Reprocessar documento", icon=":material/refresh:")
        if reprocessar:
            try:
                with st.spinner("Reprocessando o documento…"):
                    resultado = enviar("reprocessar", {"documento_id": documento["documento_id"], "origem_oci_path": selecionado, "canal_origem": canal})
                st.session_state.resultado_triagem = resultado
                st.session_state.documento_em_consulta = resultado["armazenamento_oci"]["caminho_objeto"]
                st.rerun()
            except requests.RequestException as exc:
                try:
                    detalhe = exc.response.json().get("detail") if exc.response is not None else None
                except ValueError:
                    detalhe = None
                st.error(detalhe or "Não foi possível confirmar o reprocessamento. Consulte o histórico antes de tentar novamente.")
