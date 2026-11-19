"""Padrões visuais compartilhados pelas páginas operacionais."""
import streamlit as st


DESTINOS = {
    "Prontuario_Eletronico_Paciente": "Prontuário eletrônico",
    "Farmacia_Hospitalar": "Farmácia hospitalar",
    "Auditoria_de_Autorizacoes": "Auditoria de autorizações",
    "Fila_Emergencia_Medica": "Emergência médica",
    "Auditoria_Humana": "Revisão humana",
}


def nome_destino(valor):
    return DESTINOS.get(valor, (valor or "Não informado").replace("_", " "))


def cabecalho(titulo, descricao, secao="Triagem"):
    st.caption(f"{secao} › {titulo}")
    st.title(titulo)
    st.caption(descricao)


def indicadores(itens):
    if len(itens) == 4:
        for coluna, (rotulo, valor) in zip(st.columns(4), itens):
            coluna.metric(rotulo, valor, border=True, height="stretch")
        return
    with st.container(horizontal=True):
        for rotulo, valor in itens:
            st.metric(rotulo, valor, border=True, width=220)


def estado_vazio(titulo, descricao, icone=":material/folder_open:", nova_triagem=False):
    with st.container(border=True, horizontal_alignment="center"):
        st.subheader(titulo, icon=icone)
        st.caption(descricao)
        if nova_triagem:
            st.page_link("app_pages/nova_triagem.py", label="Nova triagem", icon=":material/add_circle:")
