"""Página pública de apresentação do MediFlow."""
from base64 import b64encode
from html import escape
from pathlib import Path

import streamlit as st

assets = Path(__file__).resolve().parents[1] / "assets"
prefixo = st.get_option("server.baseUrlPath").strip("/")
caminho_painel = "/" + "/".join(filter(None, (prefixo, "central")))
logo = b64encode((assets / "mediflow.svg").read_bytes()).decode("ascii")
conteudo = (assets / "abertura.html").read_text(encoding="utf-8")
conteudo = conteudo.replace("{{logo_mediflow}}", f"data:image/svg+xml;base64,{logo}")
st.html(assets / "abertura.css")
st.html(conteudo.replace("{{caminho_painel}}", escape(caminho_painel, quote=True)))
