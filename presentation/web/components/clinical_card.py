"""Resumo clínico com a mesma hierarquia visual nas páginas do painel."""
import streamlit as st


def renderizar_resumo_clinico(dados_extraidos, classificacao):
    renderizar_classificacao(classificacao)
    renderizar_dados_extraidos(dados_extraidos)


def renderizar_classificacao(classificacao):
    prioridade = classificacao.get("nivel_prioridade", "Não informada")
    with st.container(horizontal=True):
        st.badge(prioridade, color="red" if prioridade == "Urgente" else "orange" if prioridade == "Prioritário" else "green")
        score = classificacao.get("score_confianca_classificacao")
        if score is not None:
            st.badge(f"Confiança: {score:.1%}", color="gray", icon=":material/verified:")
    st.subheader(classificacao.get("tipo_documento", "Documento clínico"))
    st.caption(classificacao.get("especialidade", "Especialidade não informada"))


def renderizar_dados_extraidos(dados_extraidos):
    paciente = dados_extraidos.get("paciente") or {}
    medico = dados_extraidos.get("medico_solicitante") or {}
    esquerda, direita = st.columns(2)
    with esquerda.container(border=True):
        st.markdown(":material/person: **Paciente**")
        st.write(paciente.get("nome") or "Não identificado")
        st.caption(f"{paciente['idade']} anos" if paciente.get("idade") is not None else "Idade não informada")
    with direita.container(border=True):
        st.markdown(":material/clinical_notes: **Profissional solicitante**")
        st.write(medico.get("nome") or "Não identificado")
        st.caption("CRM: " + (medico.get("crm") or "Não informado"))
    with st.container(border=True):
        st.markdown(":material/medical_information: **Dados extraídos**")
        st.write("**Exame:**", dados_extraidos.get("exame_realizado") or "Não informado")
        st.write("**Diagnóstico / achado:**", dados_extraidos.get("diagnostico_principal") or "Não informado")
        st.write("**CID-10 sugerido:**", dados_extraidos.get("cid_sugerido") or "Não informado")
        medicamentos = dados_extraidos.get("medicamentos") or []
        if medicamentos:
            st.write("**Medicamentos e posologias**")
            for medicamento in medicamentos:
                st.text(str(medicamento))
