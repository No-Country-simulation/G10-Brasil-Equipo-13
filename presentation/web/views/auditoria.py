"""Conferência lado a lado e homologação de pendências."""
from copy import deepcopy
import requests
import streamlit as st

from presentation.web import api_client
from presentation.web.components.pdf_viewer import renderizar_visualizador_documento
from presentation.web.components.layout import cabecalho, indicadores, estado_vazio
from presentation.web.components.documentos import chave_documento, rotulo_documento

DESTINOS = {
    "Prontuario_Eletronico_Paciente": "Prontuário eletrônico",
    "Farmacia_Hospitalar": "Farmácia hospitalar",
    "Auditoria_de_Autorizacoes": "Auditoria de autorizações",
    "Fila_Emergencia_Medica": "Emergência médica",
}


def renderizar_painel_auditoria():
    cabecalho("Revisão humana", "Compare o documento original com os dados extraídos e registre sua decisão.")
    if "aviso_auditoria" in st.session_state:
        st.success(st.session_state.pop("aviso_auditoria"))
    try:
        fila = api_client.consultar("filas/auditoria")
    except (requests.RequestException, ValueError):
        st.error("Não foi possível consultar as pendências. Tente atualizar os dados.")
        return
    indicadores([("Documentos pendentes", len(fila)), ("Falhas de extração", sum(bool(d.get("erro_extracao")) for d in fila))])
    st.caption("Revisão solicitada por dados incompletos, ambiguidade, falha de extração ou confiança inferior a 85%.")
    if not fila:
        st.session_state.pop("confirmacao_auditoria", None)
        estado_vazio("Nenhum documento pendente", "As triagens que exigirem conferência aparecerão aqui.", ":material/fact_check:")
        return
    with st.container(border=True):
        st.subheader("Selecionar pendência", icon=":material/fact_check:")
        preferido = st.session_state.pop("documento_em_revisao", None)
        registros = {chave_documento(doc): doc for doc in fila}
        rotulos = {chave: rotulo_documento(doc) for chave, doc in registros.items()}
        ids = list(registros)
        preferido = next((chave_documento(d) for d in fila if chave_documento(d) == preferido or d["documento_id"] == preferido), preferido)
        if preferido in ids:
            st.session_state.auditoria_documento_id = preferido
        elif preferido:
            st.info("O documento selecionado já não está pendente. Consulte os registros documentais.")
        if st.session_state.get("auditoria_documento_id") not in ids:
            st.session_state.auditoria_documento_id = ids[0]
        selecionado = st.selectbox("Documento para revisão", ids, key="auditoria_documento_id", format_func=rotulos.get)
    doc = registros[selecionado]
    pendente = st.session_state.get("confirmacao_auditoria")
    if pendente and pendente["original"] != doc:
        del st.session_state.confirmacao_auditoria
        st.info("A pendência selecionada ou seus dados mudaram. Prepare a decisão novamente antes de confirmar.")
    dados = doc.get("dados_extraidos", {})
    origem = doc.get("armazenamento_oci", {}).get("caminho_objeto")
    esquerda, direita = st.columns(2, gap="large")
    with esquerda, st.container(border=True):
        st.subheader("Documento original", icon=":material/description:")
        st.warning(doc.get("decisao_roteamento", {}).get("justificativa_roteamento") or "Revisão necessária.")
        score = doc.get("classificacao", {}).get("score_confianca_classificacao", 0)
        if doc.get("erro_extracao"):
            st.error("Extração não realizada: " + doc["erro_extracao"]["mensagem"])
        else:
            st.write(f"Confiança da classificação: {score:.1%}")
        bruto = doc.get("armazenamento_oci", {}).get("caminho_documento_bruto")
        if bruto:
            try:
                resp = api_client.obter_original(bruto)
                mime = resp.headers.get("content-type", "")
                tipo = "PDF" if "pdf" in mime else "IMAGEM" if "image/" in mime else "TEXTO"
                renderizar_visualizador_documento(resp.content, tipo)
            except requests.RequestException:
                st.warning("Não foi possível carregar o original. Confira o documento antes de aprovar.")
        else:
            st.info("Este registro não possui referência ao original.")
        with st.expander("Extração completa"):
            st.json(doc)
    with direita, st.container(border=True):
        st.subheader("Validação profissional", icon=":material/edit_note:")
        st.caption("Preencha os campos e escolha a decisão. Você revisará um resumo antes de confirmar o envio.")
        with st.form(f"auditoria_{selecionado}"):
            paciente = st.text_input("Nome do paciente", value=(dados.get("paciente") or {}).get("nome") or "")
            crm = st.text_input("CRM / UF", value=(dados.get("medico_solicitante") or {}).get("crm") or "", placeholder="123456-SP")
            diagnostico = st.text_input("Diagnóstico principal", value=dados.get("diagnostico_principal") or "")
            cid = st.text_input("CID-10", value=dados.get("cid_sugerido") or "")
            destino = st.selectbox("Destino após aprovação", list(DESTINOS), format_func=DESTINOS.get)
            parecer = st.text_area("Parecer do auditor", placeholder="Descreva a conferência e as correções.")
            aprovar = st.form_submit_button("Aprovar e encaminhar", type="primary", icon=":material/check_circle:", width="stretch")
            rejeitar = st.form_submit_button("Rejeitar documento", icon=":material/block:", width="stretch")
        if aprovar or rejeitar:
            st.session_state.pop("confirmacao_auditoria", None)
            if not parecer.strip() or (aprovar and (not paciente.strip() or not crm.strip())):
                st.error("Registre o parecer. Para aprovar, informe também o paciente e o CRM.")
                return
            if not origem:
                st.error("Registro sem caminho de origem. Não é possível homologar.")
                return
            payload = dict(documento_id=doc["documento_id"], origem_oci_path=origem, paciente_nome=paciente, crm_retificado=crm, diagnostico=diagnostico, cid_homologado=cid, destino_aprovado=destino, parecer_auditor=parecer.strip(), decisao="aprovar" if aprovar else "rejeitar")
            st.session_state.confirmacao_auditoria = {"payload": payload, "original": deepcopy(doc)}
        pendente = st.session_state.get("confirmacao_auditoria")
        if pendente:
            payload = pendente["payload"]
            st.subheader("Conferir decisão antes de salvar", icon=":material/rate_review:")
            st.write("**Documento:**", payload["documento_id"])
            st.write("**Decisão:**", "Aprovar e registrar destino" if payload["decisao"] == "aprovar" else "Rejeitar documento")
            campos = [
                ("Paciente", (dados.get("paciente") or {}).get("nome"), payload["paciente_nome"]),
                ("CRM / UF", (dados.get("medico_solicitante") or {}).get("crm"), payload["crm_retificado"]),
                ("Diagnóstico", dados.get("diagnostico_principal"), payload["diagnostico"]),
                ("CID-10", dados.get("cid_sugerido"), payload["cid_homologado"]),
            ]
            alteracoes = [{"Campo": nome, "Registrado": anterior or "Não informado", "Proposto": novo or "Não informado"} for nome, anterior, novo in campos if (anterior or "") != novo]
            if alteracoes:
                st.dataframe(alteracoes, hide_index=True, alt="Alterações propostas pelo auditor antes de salvar")
            else:
                st.caption("Nenhuma alteração nos campos clínicos editáveis.")
            if payload["decisao"] == "aprovar":
                st.write("**Destino proposto:**", DESTINOS[payload["destino_aprovado"]])
                st.caption("Registrar destino não comprova entrega a um sistema externo.")
            st.write("**Parecer:**", payload["parecer_auditor"])
            st.caption("Este resumo contém os valores preparados. Se editar o formulário, escolha novamente a decisão para atualizar o resumo.")
            if st.button("Cancelar confirmação", key="cancelar_auditoria", width="stretch"):
                del st.session_state.confirmacao_auditoria
                st.rerun()
            if not st.button("Confirmar e salvar decisão", key="confirmar_auditoria", type="primary", width="stretch"):
                return
            try:
                with st.spinner("Salvando a decisão…"):
                    resposta = api_client.enviar("homologar", payload)
            except (requests.RequestException, ValueError):
                del st.session_state.confirmacao_auditoria
                st.error("Não foi possível confirmar a decisão. Atualize a fila antes de tentar novamente.")
                return
            mensagem = f"Decisão salva em {resposta['caminho_novo_oci']}."
            if resposta.get("acompanhamento_fluxo_confirmado") is False:
                mensagem += " A atualização do quadro não foi confirmada; consulte as filas antes de reenviar."
            if resposta.get("notificacao_enviada") is False:
                mensagem += " O envio do alerta falhou."
            elif resposta.get("notificacao_enviada"):
                mensagem += " Notificador executado; consulte Integrações para verificar o modo de envio."
            st.session_state.aviso_auditoria = mensagem
            del st.session_state.confirmacao_auditoria
            st.rerun()
