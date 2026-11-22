"""Recebimento e conferência de documentos clínicos."""
import base64
from pathlib import Path
from uuid import uuid4

import requests
import streamlit as st

from presentation.web.api_client import enviar
from presentation.web.components.clinical_card import renderizar_classificacao, renderizar_dados_extraidos
from presentation.web.components.layout import cabecalho, estado_vazio
from presentation.web.components.pdf_viewer import renderizar_visualizador_documento
from presentation.web.components.resultado import exibir_encaminhamento, exibir_validacao


SECOES = (
    ("recebimento", "Recebimento", ":material/upload_file:"),
    ("classificacao", "Classificação", ":material/category:"),
    ("extracao", "Extração e validação", ":material/fact_check:"),
    ("resultado", "Resultado", ":material/route:"),
)
TIPOS = {"pdf": "PDF", "jpg": "IMAGEM", "jpeg": "IMAGEM", "png": "IMAGEM", "txt": "TEXTO", "json": "JSON"}


def selecionar_secao(secao):
    st.session_state.secao_triagem = secao


def reiniciar_triagem():
    st.session_state.resultado_triagem = None
    st.session_state.original_triagem = None
    st.session_state.pop("erro_triagem", None)
    st.session_state.rodada_triagem += 1
    st.session_state.novo_documento_id = f"DOC-{uuid4().hex[:12].upper()}"
    selecionar_secao("recebimento")


def solicitar_triagem():
    st.session_state.enviar_triagem = True
    st.session_state.pop("erro_triagem", None)


def estados_triagem(doc, campo_erro, enviando):
    if enviando:
        return ("Triagem em andamento", "Aguardando resposta", "Aguardando resposta", "Aguardando resposta")
    if doc is None:
        recebimento = "Confira o envio" if campo_erro else "Aguardando documento"
        resultado = "Não confirmado" if campo_erro == "resultado" else "Aguardando triagem"
        return (recebimento, "Aguardando triagem", "Aguardando triagem", resultado)

    armazenamento = doc.get("armazenamento_oci") or {}
    backup = armazenamento.get("status_backup")
    falha_extracao = bool(doc.get("erro_extracao"))
    revisao = (doc.get("decisao_roteamento") or {}).get("requer_auditoria_humana")
    if backup == "falha":
        resultado = "Relatório não salvo"
    elif doc.get("acompanhamento_fluxo_confirmado") is False:
        resultado = "Acompanhamento não confirmado"
    else:
        resultado = "Relatório salvo" if backup == "sucesso" else "Relatório não confirmado"
    return (
        "Original salvo" if armazenamento.get("caminho_documento_bruto") else "Envio recebido",
        "Indisponível" if falha_extracao else "Disponível",
        "Extração indisponível" if falha_extracao else "Revisão necessária" if revisao else "Dados disponíveis",
        resultado,
    )


def mostrar_resultado_incerto(mensagem):
    st.warning(mensagem)
    st.page_link("app_pages/filas.py", label="Consultar filas de processamento", icon=":material/view_kanban:")
    st.page_link("app_pages/documentos.py", label="Consultar documentos clínicos", icon=":material/description:")


def tratar_erro_envio(status, tipo, doc_id):
    if status == 409:
        return "duplicado", "Este ID já está cadastrado. Consulte o original em Documentos clínicos para reprocessar, ou use um novo ID para outro documento."
    if status in (401, 403):
        return "integracoes", "O serviço recusou o acesso. Confira a autorização em Armazenamento e integrações antes de tentar novamente."
    if status == 413:
        return "arquivo", "O arquivo excede o limite de envio. Reduza o tamanho e tente novamente."
    if status == 415:
        return "arquivo", "Formato não suportado. Envie PDF, JPG, JPEG, PNG, TXT ou JSON."
    if status in (400, 422):
        if tipo == "JSON":
            return "arquivo", "O arquivo não contém um JSON válido. Corrija o conteúdo, salve em UTF-8 e envie novamente."
        if tipo == "TEXTO":
            return "arquivo", "O TXT está vazio ou não pôde ser lido. Confira o conteúdo e salve o arquivo em UTF-8."
        return "arquivo", "A API recusou os dados do envio. Confira o ID, a origem e o arquivo."
    return "resultado", (
        f"Não foi possível confirmar o resultado da triagem do documento {doc_id}. "
        "Consulte Filas de processamento ou Documentos clínicos pelo ID antes de reenviar."
    )


def processar_envio(doc_id, arquivo, formato, canal):
    if not doc_id.strip():
        return "id", "Informe o ID do documento para continuar."
    if arquivo is None:
        if formato == "Fotografar documento":
            return "arquivo", "Use a câmera e capture uma foto, ou escolha Enviar arquivo."
        return "arquivo", "Selecione um arquivo para iniciar a triagem."
    bruto = arquivo.getvalue()
    if not bruto:
        return "arquivo", "O arquivo está vazio. Selecione um arquivo com conteúdo ou refaça a captura."
    extensao = arquivo.name.rsplit(".", 1)[-1].lower()
    tipo = "IMAGEM" if formato == "Fotografar documento" else TIPOS.get(extensao)
    if tipo is None:
        return "arquivo", "Formato não suportado. Envie PDF, JPG, JPEG, PNG, TXT ou JSON."
    payload = {
        "documento_id": doc_id.strip(),
        "canal_origem": canal,
        "tipo_arquivo": tipo,
        "documento_texto": None,
        "arquivo_base64": base64.b64encode(bruto).decode("ascii"),
    }
    try:
        doc = enviar("", payload)
    except requests.RequestException as exc:
        status = exc.response.status_code if exc.response is not None else None
        return tratar_erro_envio(status, tipo, doc_id.strip())
    except ValueError:
        return tratar_erro_envio(None, tipo, doc_id.strip())
    if not isinstance(doc, dict) or not doc.get("documento_id"):
        return tratar_erro_envio(None, tipo, doc_id.strip())
    st.session_state.resultado_triagem = doc
    st.session_state.original_triagem = (bruto, tipo)
    st.session_state.ultimo_documento_id = doc_id.strip()
    selecionar_secao("resultado")
    return None


def exibir_formulario(enviando, campo, mensagem):
    st.subheader("Recebimento", icon=":material/upload_file:")
    st.caption("Envie um arquivo ou fotografe o documento. A análise começa somente ao executar a triagem.")
    formato = st.segmented_control("Entrada", ["Enviar arquivo", "Fotografar documento"], default="Enviar arquivo")
    with st.form("nova_triagem", border=False):
        arquivo = None
        if formato == "Enviar arquivo":
            arquivo = st.file_uploader("Documento clínico", type=list(TIPOS), key=f"arquivo_{st.session_state.rodada_triagem}")
            st.caption("Formatos aceitos: PDF, JPG, JPEG, PNG, TXT e JSON.")
        else:
            apresentacao = (st.session_state.get("integracoes") or {}).get("apresentacao", {})
            simulacao = apresentacao.get("ativa") and not apresentacao.get("llm_real")
            st.caption("Permita o acesso à câmera no navegador. Enquadre uma página inteira, com boa iluminação e texto legível. Se a câmera estiver indisponível, use Enviar arquivo.")
            if simulacao:
                st.info("A análise simulada reconhece somente os exemplos TXT. Use Enviar arquivo; fotografias exigem análise real com Gemini.")
            arquivo = st.camera_input("Fotografar documento", resolution="1080p", key=f"camera_{st.session_state.rodada_triagem}", disabled=bool(simulacao))
        if campo == "arquivo":
            st.error(mensagem)
        identificacao, origem = st.columns(2)
        with identificacao:
            doc_id = st.text_input("ID do documento", key="novo_documento_id")
            if campo in {"id", "duplicado"}:
                st.error(mensagem)
        with origem:
            canal = st.selectbox("Canal de origem", ["Pronto_Socorro", "Ambulatorio", "Recepcao"], format_func=lambda valor: {"Pronto_Socorro": "Pronto-socorro", "Ambulatorio": "Ambulatório", "Recepcao": "Recepção"}[valor])
        falha_configuracao = any(item["estado"] == "erro" and item["recurso"] in {"Gemini", "Armazenamento"} for item in st.session_state.get("diagnostico", {}).get("itens", []))
        st.form_submit_button(
            "Executar triagem", type="primary", icon=":material/scan:", width="stretch",
            disabled=falha_configuracao or enviando, on_click=solicitar_triagem,
        )
        if enviando:
            st.info("Triagem em andamento. Aguarde a confirmação do resultado.")
        if falha_configuracao:
            st.caption("Corrija a configuração indicada em Armazenamento e integrações e atualize o diagnóstico para liberar novas análises.")
    if campo == "duplicado":
        st.page_link("app_pages/documentos.py", label="Consultar documentos clínicos", icon=":material/description:")
    if campo == "integracoes":
        st.error(mensagem)
        st.page_link("app_pages/integracoes.py", label="Abrir armazenamento e integrações", icon=":material/cloud:")
    if campo == "resultado":
        mostrar_resultado_incerto(mensagem)
    if enviando:
        erro = processar_envio(doc_id, arquivo, formato, canal)
        if erro:
            st.session_state.erro_triagem = erro
        st.rerun()


def exibir_recebimento(doc):
    st.subheader("Recebimento", icon=":material/upload_file:")
    st.write("**Documento:**", doc.get("documento_id", "Não informado"))
    st.write("**Origem:**", (doc.get("canal_origem") or "Não registrada").replace("_", " "))
    if (doc.get("armazenamento_oci") or {}).get("caminho_documento_bruto"):
        st.success("Original salvo.")
    else:
        st.info("Armazenamento do original não confirmado.")
    if st.session_state.original_triagem:
        with st.expander("Conferir documento enviado", icon=":material/visibility:"):
            renderizar_visualizador_documento(*st.session_state.original_triagem)


cabecalho("Nova triagem documental", "Organize a entrada do documento e acompanhe a classificação, a extração e o encaminhamento.", "Documentos clínicos")
doc = st.session_state.resultado_triagem
enviando = st.session_state.pop("enviar_triagem", False)
campo, mensagem = st.session_state.get("erro_triagem", (None, ""))
secao = st.session_state.get("secao_triagem", "resultado" if doc is not None else "recebimento")
estados = estados_triagem(doc, campo, enviando)
for coluna, (chave, rotulo, icone), estado in zip(st.columns(4), SECOES, estados):
    with coluna:
        disponivel = chave == "recebimento" or doc is not None or (chave == "resultado" and campo == "resultado")
        st.button(rotulo, key=f"secao_triagem_{chave}", icon=icone, width="stretch",
                  type="primary" if secao == chave else "secondary",
                  disabled=enviando or not disponivel, on_click=selecionar_secao, args=(chave,))
        st.caption(estado)

with st.container(border=True):
    if secao == "recebimento":
        if doc is not None:
            exibir_recebimento(doc)
        else:
            if (st.session_state.get("integracoes") or {}).get("apresentacao", {}).get("ativa"):
                st.info("Baixe um exemplo e envie-o no campo de upload. Os cenários são fictícios. Na análise simulada, mantenha o conteúdo TXT original.")
                with st.container(horizontal=True):
                    for nome, rotulo in [("rotina", "Rotina"), ("urgencia", "Urgência"), ("revisao", "Revisão humana")]:
                        exemplo = Path(__file__).resolve().parents[3] / "presentation_examples" / f"{nome}.txt"
                        st.download_button(f"Exemplo: {rotulo}", exemplo.read_bytes(), file_name=f"{nome}.txt", mime="text/plain")
            exibir_formulario(enviando, campo, mensagem)
    elif secao == "resultado" and doc is None and campo == "resultado":
        st.subheader("Resultado ainda não confirmado")
        mostrar_resultado_incerto(mensagem)
    elif doc is None:
        estado_vazio("Aguardando triagem", "Envie um documento na seção Recebimento.")
    elif secao == "classificacao":
        st.subheader("Classificação", icon=":material/category:")
        if doc.get("erro_extracao"):
            st.warning("Classificação indisponível. Consulte Extração e validação para entender a falha.")
        else:
            renderizar_classificacao(doc.get("classificacao") or {})
            st.caption("A confiança é uma estimativa do modelo para a classificação.")
    elif secao == "extracao":
        st.subheader("Extração e validação", icon=":material/fact_check:")
        falha = doc.get("erro_extracao")
        if falha:
            st.error("Extração não realizada. " + falha.get("mensagem", "A análise automática falhou."))
            st.caption("Consulte Resultado para verificar se o documento foi salvo para revisão humana.")
        else:
            renderizar_dados_extraidos(doc.get("dados_extraidos") or {})
            st.markdown("**Pendências de validação**")
            exibir_validacao(doc)
            decisao = doc.get("decisao_roteamento") or {}
            if decisao.get("requer_auditoria_humana") and decisao.get("justificativa_roteamento"):
                st.info(decisao["justificativa_roteamento"])
    else:
        st.subheader("Resultado da triagem", icon=":material/route:")
        st.caption("Documento: " + str(doc.get("documento_id", "Não informado")))
        if doc.get("erro_extracao"):
            st.error("Extração não realizada. Abra Extração e validação para conferir o motivo.")
        exibir_encaminhamento(doc)

    if doc is not None:
        st.divider()
        iniciar, consultar = st.columns(2)
        with iniciar:
            st.button(
                "Iniciar nova triagem", icon=":material/add:", width="stretch",
                on_click=reiniciar_triagem,
            )
        with consultar:
            if st.button("Consultar documentos", icon=":material/description:", width="stretch"):
                st.switch_page("app_pages/documentos.py")
