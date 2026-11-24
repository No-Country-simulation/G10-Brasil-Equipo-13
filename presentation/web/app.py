"""Entrada do painel operacional MediFlow."""
from uuid import uuid4
from pathlib import Path
import os
import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv(override=False)

from presentation.web.api_client import consultar
from presentation.web.auth import exigir_login
from presentation.web.components.diagnostico import carregar_diagnostico

st.set_page_config(page_title="MediFlow", page_icon=":material/health_and_safety:", layout="wide")
abertura = st.Page("app_pages/abertura.py", title="MediFlow | Abertura", default=True, visibility="hidden")
central = st.Page("app_pages/central.py", title="Central de triagem", icon=":material/dashboard:")
paginas_operacionais = {
    "Triagem": [
        central,
        st.Page("app_pages/documentos.py", title="Documentos clínicos", icon=":material/description:"),
        st.Page("app_pages/nova_triagem.py", title="Nova triagem", icon=":material/upload_file:"),
        st.Page("app_pages/filas.py", title="Filas de processamento", icon=":material/view_kanban:"),
        st.Page("app_pages/urgencias.py", title="Urgências", icon=":material/emergency:"),
        st.Page("app_pages/auditoria.py", title="Revisão humana", icon=":material/fact_check:"),
    ],
    "Plataforma": [st.Page("app_pages/integracoes.py", title="Armazenamento e integrações", icon=":material/cloud:")],
}
pagina = st.navigation(
    [abertura, *(destino for grupo in paginas_operacionais.values() for destino in grupo)],
    position="hidden",
)

if pagina == abertura:
    # O retorno do login OIDC chega à raiz em uma nova sessão.
    if getattr(st.user, "is_logged_in", False):
        st.switch_page(central)
    abertura.run()
    st.stop()

st.set_page_config(page_title="MediFlow | Central de triagem")
autenticado = exigir_login()
if "diagnostico" not in st.session_state:
    carregar_diagnostico()
for chave, valor in {"resultado_triagem": None, "original_triagem": None, "rodada_triagem": 0, "novo_documento_id": f"DOC-{uuid4().hex[:12].upper()}"}.items():
    st.session_state.setdefault(chave, valor)

assets = Path(__file__).parent / "assets"
st.logo(str(assets / "mediflow.svg"), icon_image=str(assets / "icone.svg"), size="large")

try:
    integracoes = consultar("integracoes")
except (requests.RequestException, ValueError):
    integracoes = None
st.session_state.integracoes = integracoes
apresentacao = (integracoes or {}).get("apresentacao", st.session_state.get("diagnostico", {}).get("apresentacao", {}))
if apresentacao.get("ativa"):
    analise = "análise real com Gemini" if apresentacao.get("llm_real") else "análise simulada · sem chamadas à LLM"
    st.warning(f"🟡 MODO APRESENTAÇÃO · {analise}. Use somente documentos fictícios. Dados em memória, perdidos ao reiniciar a API. Alertas externos desabilitados.")
with st.sidebar:
    for secao, destinos in paginas_operacionais.items():
        st.caption(secao)
        for destino in destinos:
            st.page_link(destino)
    ambiente = {"local": "Local", "cloud": "Cloud"}.get(os.getenv("APP_ENV", "local").strip().lower(), "Não reconhecido")
    st.caption(f"Ambiente: {ambiente}")
    st.caption("Modo: " + ("Apresentação" if apresentacao.get("ativa") else "Operacional" if integracoes else "Não confirmado"))
    st.caption("Autenticação: " + ("Ativada" if autenticado else "Desativada"))
    if integracoes:
        modo = integracoes["armazenamento"]["modo"]
        nomes = {"simulado": "Memória", "emulador_oci": "Emulador OCI", "oci": "OCI"}
        st.caption("Armazenamento: " + nomes.get(modo, "Não reconhecido"))
        if modo == "simulado":
            st.warning("Dados perdidos ao reiniciar a API.")
    else:
        st.caption("Armazenamento: Indisponível")
        st.warning("API indisponível")
    if st.button("Atualizar dados", icon=":material/refresh:", width="stretch"):
        carregar_diagnostico()
        st.rerun()
problemas = [item for item in st.session_state.get("diagnostico", {}).get("itens", []) if item["estado"] == "erro"]
if problemas:
    st.warning("Configuração requer atenção. Consulte Armazenamento e integrações para orientações.")
    with st.expander("Ver problemas identificados"):
        for item in problemas:
            st.write(f"**{item['recurso']}:** {item['mensagem']}")
            st.caption(item.get("orientacao", ""))
pagina.run()
