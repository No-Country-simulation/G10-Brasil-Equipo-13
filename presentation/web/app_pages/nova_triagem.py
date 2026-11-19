"""Recebimento e conferência de documentos clínicos."""
import base64
from uuid import uuid4
import requests
import streamlit as st
from presentation.web.api_client import enviar
from presentation.web.components.resultado import exibir_resultado
from presentation.web.components.pdf_viewer import renderizar_visualizador_documento
from presentation.web.components.layout import cabecalho, etapas_triagem, estado_vazio


def reiniciar_triagem():
    st.session_state.resultado_triagem = None
    st.session_state.original_triagem = None
    st.session_state.rodada_triagem += 1
    st.session_state.novo_documento_id = f"DOC-{uuid4().hex[:12].upper()}"


cabecalho("Nova triagem documental", "Organize a entrada do documento e acompanhe a classificação, a extração e o encaminhamento.", "Documentos clínicos")
if (st.session_state.get("integracoes") or {}).get("apresentacao", {}).get("ativa"):
    from pathlib import Path
    st.info("Baixe um exemplo e envie-o no campo de upload. Os cenários são fictícios. Na análise simulada, mantenha o conteúdo TXT original.")
    with st.container(horizontal=True):
        for nome, rotulo in [("rotina", "Rotina"), ("urgencia", "Urgência"), ("revisao", "Revisão humana")]:
            exemplo = Path(__file__).resolve().parents[3] / "presentation_examples" / f"{nome}.txt"
            st.download_button(f"Exemplo: {rotulo}", exemplo.read_bytes(), file_name=f"{nome}.txt", mime="text/plain")
etapas = st.container()
with st.container(border=True):
    st.subheader("Recebimento", icon=":material/upload_file:")
    st.caption("Envie um arquivo ou fotografe o documento. A análise começa somente ao executar a triagem.")
    formato = st.segmented_control("Entrada", ["Enviar arquivo", "Fotografar documento"], default="Enviar arquivo")
    with st.form("nova_triagem", border=False):
        arquivo = None
        if formato == "Enviar arquivo":
            arquivo = st.file_uploader("Documento clínico", type=["pdf", "jpg", "jpeg", "png", "txt"], key=f"arquivo_{st.session_state.rodada_triagem}")
            st.caption("Formatos aceitos: PDF, JPG, PNG e TXT.")
        else:
            apresentacao = (st.session_state.get("integracoes") or {}).get("apresentacao", {})
            simulacao = apresentacao.get("ativa") and not apresentacao.get("llm_real")
            st.caption("Permita o acesso à câmera no navegador. Enquadre uma página inteira, com boa iluminação e texto legível. Se a câmera estiver indisponível, use Enviar arquivo.")
            if simulacao:
                st.info("A análise simulada reconhece somente os exemplos TXT. Use Enviar arquivo; fotografias exigem análise real com Gemini.")
            arquivo = st.camera_input("Fotografar documento", resolution="1080p", key=f"camera_{st.session_state.rodada_triagem}", disabled=bool(simulacao))
        identificacao, origem = st.columns(2)
        with identificacao:
            doc_id = st.text_input("ID do documento", key="novo_documento_id")
        with origem:
            canal = st.selectbox("Canal de origem", ["Pronto_Socorro", "Ambulatorio", "Recepcao"], format_func=lambda valor: {"Pronto_Socorro": "Pronto-socorro", "Ambulatorio": "Ambulatório", "Recepcao": "Recepção"}[valor])
        falha_configuracao = any(item["estado"] == "erro" and item["recurso"] in {"Gemini", "Armazenamento"} for item in st.session_state.get("diagnostico", {}).get("itens", []))
        processar = st.form_submit_button("Executar triagem", type="primary", icon=":material/scan:", width="stretch", disabled=falha_configuracao)
        if falha_configuracao:
            st.caption("Corrija a configuração indicada em Armazenamento e integrações e atualize o diagnóstico para liberar novas análises.")

if processar:
    if not doc_id.strip() or arquivo is None:
        st.error("Informe o ID e envie um arquivo ou capture uma foto do documento.")
    else:
        try:
            bruto = arquivo.getvalue()
            if not bruto:
                raise ValueError("Documento vazio")
            nome = arquivo.name.lower()
            tipo = "IMAGEM" if formato == "Fotografar documento" else "PDF" if nome.endswith(".pdf") else "IMAGEM" if nome.endswith((".jpg", ".jpeg", ".png")) else "TEXTO"
            textual = bruto.decode("utf-8-sig") if tipo == "TEXTO" else None
            payload = {"documento_id": doc_id.strip(), "canal_origem": canal, "tipo_arquivo": tipo, "documento_texto": textual, "arquivo_base64": base64.b64encode(bruto).decode("ascii") if textual is None else None}
            st.session_state.resultado_triagem = None
            st.session_state.original_triagem = None
            with st.spinner("Extraindo dados e avaliando o encaminhamento…"):
                doc = enviar("", payload)
            st.session_state.resultado_triagem = doc
            st.session_state.original_triagem = (bruto, tipo)
            st.session_state.ultimo_documento_id = doc_id.strip()
        except (ValueError, UnicodeDecodeError):
            st.error("Documento vazio ou conteúdo inválido. Para arquivos TXT, use codificação UTF-8.")
        except requests.RequestException as exc:
            if exc.response is not None and exc.response.status_code == 409:
                st.error("Este ID já está cadastrado. Abra o registro em Documentos clínicos e use Reprocessar documento, ou informe outro ID para um novo documento.")
            else:
                st.error("Não foi possível concluir a triagem. Verifique a API antes de reenviar.")

with etapas:
    etapas_triagem(st.session_state.resultado_triagem)

if st.session_state.resultado_triagem:
    with st.container(horizontal=True):
        st.button("Iniciar outra triagem", icon=":material/add:", on_click=reiniciar_triagem)
        st.page_link("app_pages/documentos.py", label="Consultar documentos", icon=":material/description:")
    if st.session_state.original_triagem:
        with st.expander("Conferir documento enviado", icon=":material/visibility:"):
            renderizar_visualizador_documento(*st.session_state.original_triagem)
    with st.container(border=True):
        st.subheader("Resultado da triagem", icon=":material/route:")
        exibir_resultado(st.session_state.resultado_triagem)
else:
    estado_vazio("Aguardando documento", "O resultado mostrará os dados extraídos, a confiança e o motivo do encaminhamento.", ":material/scan:")
