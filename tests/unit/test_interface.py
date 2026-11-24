"""Regressões de navegação e leitura dos estados reais no painel."""
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from streamlit.testing.v1 import AppTest


INTEGRACOES = {
    "armazenamento": {"modo": "emulador_oci", "bucket": "testes", "conexao": "não verificada"},
    "ia": {"provedor": "Google Gemini", "modelo": "teste", "conexao": "não verificada"},
    "alertas": {"modo": "somente_log", "entrega": "não verificada"},
}
DOCUMENTO = {
    "documento_id": "DOC-TESTE", "status": "erro",
    "erro_extracao": {"codigo": "indisponivel", "mensagem": "Serviço indisponível"},
    "dados_extraidos": {"paciente": {"nome": None}},
    "classificacao": {"nivel_prioridade": "Urgente"},
    "decisao_roteamento": {"requer_auditoria_humana": True, "destino_principal": "Auditoria_Humana"},
}


def test_central_exibe_registros_sem_contar_falha_como_urgencia():
    def consultar(caminho):
        return INTEGRACOES if caminho == "integracoes" else [DOCUMENTO]

    with patch("presentation.web.api_client.consultar", side_effect=consultar):
        app = AppTest.from_file(Path(__file__).resolve().parents[2] / "presentation/web/app.py", default_timeout=30).run()
        app.switch_page("app_pages/central.py").run()
        assert not app.exception
        assert [m.value for m in app.metric] == ["1", "1", "0", "1"]
        assert app.dataframe[0].value.iloc[0]["Prioridade"] == "Não avaliada"
        app.text_input[0].set_value("inexistente").run()
        assert not app.dataframe
        assert "Nenhum documento" in app.info[0].value


def test_vazio_e_indisponibilidade_sao_estados_diferentes():
    with patch("presentation.web.api_client.consultar", side_effect=lambda caminho: INTEGRACOES if caminho == "integracoes" else []):
        app = AppTest.from_file(Path(__file__).resolve().parents[2] / "presentation/web/app.py", default_timeout=30).run()
        app.switch_page("app_pages/central.py").run()
        assert not app.exception
        assert any("primeira triagem" in s.value for s in app.subheader)
        with patch("presentation.web.api_client.consultar", side_effect=requests.ConnectionError):
            app.run()
            assert app.error
            assert not app.metric


def test_paginas_acessiveis_e_documento_ausente_nao_enviado():
    with patch("presentation.web.api_client.consultar", side_effect=lambda caminho: INTEGRACOES if caminho == "integracoes" else []), patch("presentation.web.api_client.enviar") as enviar:
        app = AppTest.from_file(Path(__file__).resolve().parents[2] / "presentation/web/app.py", default_timeout=30).run()
        for pagina in ("documentos", "filas", "urgencias", "auditoria", "integracoes", "nova_triagem"):
            app.switch_page(f"app_pages/{pagina}.py").run()
            assert not app.exception
        assert list(app.segmented_control[0].options) == ["Enviar arquivo", "Fotografar documento"]
        app.segmented_control[0].set_value("Fotografar documento").run()
        next(b for b in app.button if b.label == "Executar triagem").click().run()
        assert "capture uma foto" in app.error[0].value
        enviar.assert_not_called()


def test_camera_envia_imagem_apenas_ao_confirmar_triagem():
    import base64
    captura = SimpleNamespace(name="captura.jpg", getvalue=lambda: b"imagem-de-teste")
    with patch("presentation.web.api_client.consultar", side_effect=lambda caminho: INTEGRACOES if caminho == "integracoes" else []), patch("presentation.web.api_client.enviar", return_value=DOCUMENTO) as enviar, patch("streamlit.camera_input", return_value=captura), patch("presentation.web.components.pdf_viewer.renderizar_visualizador_documento"):
        app = AppTest.from_file(Path(__file__).resolve().parents[2] / "presentation/web/app.py", default_timeout=30).run()
        app.switch_page("app_pages/nova_triagem.py").run()
        app.segmented_control[0].set_value("Fotografar documento").run()
        enviar.assert_not_called()
        next(b for b in app.button if b.label == "Executar triagem").click().run()
        assert not app.exception
        enviar.assert_called_once()
        payload = enviar.call_args.args[1]
        assert payload["tipo_arquivo"] == "IMAGEM"
        assert payload["documento_texto"] is None
        assert base64.b64decode(payload["arquivo_base64"]) == b"imagem-de-teste"

        assert app.session_state.secao_triagem == "resultado"
        assert "Resultado da triagem" in [item.value for item in app.subheader]
        app.button(key="secao_triagem_classificacao").click().run()
        assert any("Classificação indisponível" in item.value for item in app.warning)
        app.button(key="secao_triagem_extracao").click().run()
        assert any("Extração não realizada" in item.value for item in app.error)
        app.button(key="secao_triagem_recebimento").click().run()
        assert "Recebimento" in [item.value for item in app.subheader]
        assert "Consultar documentos" in [item.label for item in app.button]
        next(b for b in app.button if b.label == "Iniciar nova triagem").click().run()
        assert app.session_state.resultado_triagem is None
        assert app.session_state.secao_triagem == "recebimento"
        assert "Executar triagem" in [item.label for item in app.button]
        enviar.assert_called_once()


@pytest.mark.parametrize("status", [422, 409, None])
def test_envio_invalido_ou_incerto_mantem_o_formulario(status):
    arquivo = SimpleNamespace(name="caso.json", getvalue=lambda: b'{"documento": 1}')
    if status is None:
        erro = requests.Timeout("detalhe interno")
    else:
        resposta = requests.Response()
        resposta.status_code = status
        erro = requests.HTTPError("detalhe interno", response=resposta)
    with (
        patch("presentation.web.api_client.consultar", side_effect=lambda caminho: INTEGRACOES if caminho == "integracoes" else []),
        patch("presentation.web.api_client.enviar", side_effect=erro) as enviar,
        patch("streamlit.file_uploader", return_value=arquivo),
    ):
        app = AppTest.from_file(Path(__file__).resolve().parents[2] / "presentation/web/app.py", default_timeout=30).run()
        app.switch_page("app_pages/nova_triagem.py").run()
        app.text_input(key="novo_documento_id").set_value("DOC-ENVIO")
        next(b for b in app.button if b.label == "Executar triagem").click().run()
        assert not app.exception
        assert app.session_state.resultado_triagem is None
        assert app.text_input(key="novo_documento_id").value == "DOC-ENVIO"
        assert enviar.call_args.args[1]["tipo_arquivo"] == "JSON"
        if status is None:
            assert any("DOC-ENVIO" in item.value and "antes de reenviar" in item.value for item in app.warning)
            app.button(key="secao_triagem_resultado").click().run()
            assert "Resultado ainda não confirmado" in [item.value for item in app.subheader]
        elif status == 422:
            assert any("JSON válido" in item.value for item in app.error)
        else:
            assert any("ID já está cadastrado" in item.value for item in app.error)
        enviar.assert_called_once()


def test_resultado_com_relatorio_nao_salvo_orienta_consultar_filas():
    doc = {
        **DOCUMENTO,
        "armazenamento_oci": {"status_backup": "falha", "caminho_documento_bruto": "recebidos/caso.json"},
        "acompanhamento_fluxo_confirmado": False,
    }
    with patch("presentation.web.api_client.consultar", side_effect=lambda caminho: INTEGRACOES if caminho == "integracoes" else []):
        app = AppTest.from_file(Path(__file__).resolve().parents[2] / "presentation/web/app.py", default_timeout=30).run()
        app.session_state.resultado_triagem = doc
        app.session_state.secao_triagem = "resultado"
        app.switch_page("app_pages/nova_triagem.py").run()
        assert not app.exception
        assert any("O relatório não foi salvo" in item.value and "Filas" in item.value for item in app.error)
        assert any("acompanhamento não foi confirmado" in item.value for item in app.warning)
        assert not app.success
        assert all(link.proto.label != "Abrir revisão humana" for link in app.get("page_link"))


def test_filtros_documentais_combinam_prioridade_e_revisao():
    rotina = {
        "documento_id": "DOC-ROTINA", "status": "processado",
        "classificacao": {"tipo_documento": "Receituário", "nivel_prioridade": "Rotina"},
        "dados_extraidos": {"paciente": {"nome": "Paciente de teste"}},
        "decisao_roteamento": {"requer_auditoria_humana": False},
    }
    with patch("presentation.web.api_client.consultar", side_effect=lambda caminho: INTEGRACOES if caminho == "integracoes" else [DOCUMENTO, rotina]):
        app = AppTest.from_file(Path(__file__).resolve().parents[2] / "presentation/web/app.py", default_timeout=30).run()
        app.switch_page("app_pages/documentos.py").run()
        assert not app.exception
        next(s for s in app.selectbox if s.label == "Prioridade").select("Não avaliada").run()
        assert list(app.dataframe[0].value["Documento"]) == ["DOC-TESTE"]
        next(s for s in app.selectbox if s.label == "Necessidade de revisão").select("Sem revisão pendente").run()
        assert not app.dataframe
        assert any(s.value == "Nenhum documento encontrado" for s in app.subheader)


def test_revisao_preenchida_preserva_validacao_antes_do_envio():
    with patch("presentation.web.api_client.consultar", side_effect=lambda caminho: {"integracoes": INTEGRACOES, "homologacoes/pendentes": []}.get(caminho, [DOCUMENTO])), patch("presentation.web.api_client.enviar") as enviar:
        app = AppTest.from_file(Path(__file__).resolve().parents[2] / "presentation/web/app.py", default_timeout=30).run()
        app.switch_page("app_pages/auditoria.py").run()
        assert not app.exception
        next(b for b in app.button if b.label == "Aprovar e encaminhar").click().run()
        assert any("Registre o parecer" in e.value for e in app.error)
        enviar.assert_not_called()


def test_kanban_abre_pendencia_correta_e_mantem_selecao_ao_editar():
    from copy import deepcopy
    doc_a, doc_b = deepcopy(DOCUMENTO), deepcopy(DOCUMENTO)
    doc_a["documento_id"], doc_b["documento_id"] = "DOC-A", "DOC-B"
    itens = [{"documento_id": d["documento_id"], "etapa": "revisao_humana", "documento": d} for d in (doc_a, doc_b)]

    def consulta(caminho):
        return {"integracoes": INTEGRACOES, "filas/processamento": itens, "homologacoes/pendentes": []}.get(caminho, [doc_a, doc_b])

    with patch("presentation.web.api_client.consultar", side_effect=consulta):
        app = AppTest.from_file(Path(__file__).resolve().parents[2] / "presentation/web/app.py", default_timeout=30).run()
        app.switch_page("app_pages/filas.py").run()
        assert not app.exception
        next(b for b in app.button if b.key == "revisar_DOC-B_None").click().run()
        assert not app.exception
        assert next(s for s in app.selectbox if s.label == "Documento para revisão").value == "DOC-B"
        # O AppTest precisa fixar a página ativa depois do redirecionamento
        # disparado por um botão dentro de um fragmento.
        app.switch_page("app_pages/auditoria.py").run()
        next(t for t in app.text_input if t.label == "Nome do paciente").set_value("Paciente conferido").run()
        assert not app.exception
        assert next(s for s in app.selectbox if s.label == "Documento para revisão").value == "DOC-B"


def test_kanban_offline_nao_exibe_contagens_ficticias():
    with patch("presentation.web.api_client.consultar", side_effect=requests.ConnectionError):
        app = AppTest.from_file(Path(__file__).resolve().parents[2] / "presentation/web/app.py", default_timeout=30).run()
        app.switch_page("app_pages/filas.py").run()
        assert not app.exception
        assert app.error and not app.metric
