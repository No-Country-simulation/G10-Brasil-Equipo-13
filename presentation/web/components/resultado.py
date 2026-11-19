"""Apresentação consistente da decisão e da extração clínica."""
import json
import streamlit as st
from presentation.web.components.clinical_card import renderizar_resumo_clinico
from presentation.web.components.documentos import estado_documento
from presentation.web.components.layout import nome_destino


def campos_nao_identificados(dados):
    """Ausência de informação registrada, sem inferir ilegibilidade ou obrigação."""
    campos = []
    for grupo, chave, rotulo in [
        ("paciente", "nome", "Nome do paciente"),
        ("paciente", "idade", "Idade do paciente"),
        ("medico_solicitante", "nome", "Nome do profissional solicitante"),
        ("medico_solicitante", "crm", "CRM do profissional solicitante"),
    ]:
        valor = (dados.get(grupo) or {}).get(chave)
        if valor is None or isinstance(valor, str) and not valor.strip():
            campos.append(rotulo)
    return campos


def resumo_triagem(doc):
    classificacao = doc.get("classificacao") or {}
    falha = bool(doc.get("erro_extracao"))
    score = classificacao.get("score_confianca_classificacao")
    with st.container(border=True):
        st.subheader("Resumo da triagem", icon=":material/summarize:")
        st.caption("Documento: " + str(doc.get("documento_id", "Não informado")))
        with st.container(horizontal=True):
            valores = [
                ("Categoria", "Não avaliada" if falha else classificacao.get("tipo_documento") or "Não identificada"),
                ("Especialidade", "Não avaliada" if falha else classificacao.get("especialidade") or "Não identificada"),
                ("Confiança da classificação", "Não avaliada" if falha else f"{score:.1%}" if isinstance(score, (int, float)) and 0 <= score <= 1 else "Não informada"),
                ("Origem", str(doc.get("canal_origem") or "Não registrada").replace("_", " ")),
            ]
            for rotulo, valor in valores:
                with st.container(border=True, width=220):
                    st.caption(rotulo)
                    st.text(valor)
        st.caption("A confiança é uma estimativa do modelo para a classificação; não comprova correção clínica.")
        if not falha:
            exibir_validacao(doc)


def exibir_validacao(doc):
    pendentes = campos_nao_identificados(doc.get("dados_extraidos") or {})
    revisao = bool((doc.get("decisao_roteamento") or {}).get("requer_auditoria_humana"))
    if pendentes:
        st.markdown("**Campos não identificados no resultado**")
        for campo in pendentes:
            st.text("• " + campo)
        st.caption("Ausência no resultado não comprova ausência no original ou ilegibilidade. A necessidade desses campos depende do documento.")
    if revisao:
        st.warning("Revisão humana necessária. Confira os dados e o motivo indicado na decisão.")
    elif not pendentes:
        st.caption("Identificação do paciente e do profissional preenchida no resultado; conteúdo ainda sujeito à conferência.")


def exibir_resultado(doc):
    estado = estado_documento(doc)
    cores = {"Falha na extração": "red", "Erro": "red", "Aguardando revisão": "orange", "Processado": "green"}
    st.badge(estado, color=cores.get(estado, "gray"))
    resumo_triagem(doc)
    if doc.get("erro_extracao"):
        st.error("Extração não realizada: " + doc["erro_extracao"]["mensagem"])
        st.caption("A prioridade clínica não foi avaliada.")
    else:
        renderizar_resumo_clinico(doc.get("dados_extraidos", {}), doc.get("classificacao", {}))
    exibir_encaminhamento(doc)


def exibir_encaminhamento(doc):
    armazenamento = doc.get("armazenamento_oci") or {}
    backup = armazenamento.get("status_backup")
    if doc.get("acompanhamento_fluxo_confirmado") is False:
        st.warning("O resultado foi recebido, mas o acompanhamento não foi confirmado. Consulte Filas de processamento antes de reenviar.")
    decisao = doc.get("decisao_roteamento") or {}
    with st.container(border=True):
        st.subheader("Encaminhamento", icon=":material/route:")
        rotulo = "Destino definido" if backup == "sucesso" else "Destino indicado pela triagem"
        st.write(f"**{rotulo}:**", nome_destino(decisao.get("destino_principal")))
        mensagem = decisao.get("justificativa_roteamento") or "Sem justificativa informada."
        if decisao.get("requer_auditoria_humana"):
            st.warning(mensagem)
            if backup == "sucesso":
                st.page_link("app_pages/auditoria.py", label="Abrir revisão humana", icon=":material/fact_check:")
        elif doc.get("classificacao", {}).get("nivel_prioridade") == "Urgente":
            st.warning(mensagem)
        else:
            st.info(mensagem)
        if backup == "falha":
            st.error("O relatório não foi salvo. Consulte Filas de processamento pelo ID antes de reenviar.")
        elif backup == "sucesso":
            st.success("Relatório salvo para revisão humana." if decisao.get("requer_auditoria_humana") else "Relatório salvo.")
        else:
            st.info("Armazenamento do relatório não confirmado.")
        if backup != "sucesso" or doc.get("acompanhamento_fluxo_confirmado") is False:
            st.page_link("app_pages/filas.py", label="Consultar filas de processamento", icon=":material/view_kanban:")
        if decisao.get("notificacao_gerada"):
            st.caption("Alerta gerado. A entrega externa não é comprovada por este registro.")
    with st.expander("Dados estruturados e armazenamento", icon=":material/data_object:"):
        st.caption(f"Objeto: {armazenamento.get('caminho_objeto', 'Não informado')}")
        st.json(doc)
    st.download_button("Baixar resultado JSON", json.dumps(doc, ensure_ascii=False, indent=2), file_name=f"{doc.get('documento_id', 'triagem')}.json", mime="application/json", icon=":material/download:")
