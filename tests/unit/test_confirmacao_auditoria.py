from copy import deepcopy
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


DOCUMENTO = {
    "documento_id": "DOC-TESTE", "execucao_id": "exec-1",
    "dados_extraidos": {"paciente": {"nome": "Paciente A"}, "medico_solicitante": {"crm": "123-SP"}},
    "armazenamento_oci": {"caminho_objeto": "auditoria_humana/teste.json"},
}


def iniciar():
    return AppTest.from_string('''
from presentation.web.views.auditoria import renderizar_painel_auditoria
renderizar_painel_auditoria()
''', default_timeout=30).run()


def botao(app, rotulo):
    return next(b for b in app.button if b.label == rotulo)


def preparar(app, decisao="Aprovar e encaminhar"):
    app.text_input[0].set_value("Paciente conferido")
    app.text_area[0].set_value("Conferido com original.")
    botao(app, decisao).click().run()
    assert not app.exception


def test_aprovacao_so_envia_apos_confirmacao_com_resumo_das_alteracoes():
    fila = [deepcopy(DOCUMENTO)]
    with patch("presentation.web.api_client.consultar", side_effect=lambda caminho: fila if caminho == "filas/auditoria" else []), patch("presentation.web.api_client.enviar") as enviar:
        app = iniciar()
        preparar(app)
        enviar.assert_not_called()
        assert app.dataframe[0].value.iloc[0]["Registrado"] == "Paciente A"
        assert app.dataframe[0].value.iloc[0]["Proposto"] == "Paciente conferido"
        def salvar(*args):
            fila.clear()
            return {"caminho_novo_oci": "processados/teste.json"}
        enviar.side_effect = salvar
        botao(app, "Confirmar e salvar decisão").click().run()
        assert not app.exception
        enviar.assert_called_once()
        assert enviar.call_args.args[1]["paciente_nome"] == "Paciente conferido"
        assert enviar.call_args.args[1]["decisao"] == "aprovar"


def test_cancelar_rejeicao_nao_envia_e_preserva_edicao():
    with patch("presentation.web.api_client.consultar", side_effect=lambda caminho: [DOCUMENTO] if caminho == "filas/auditoria" else []), patch("presentation.web.api_client.enviar") as enviar:
        app = iniciar()
        preparar(app, "Rejeitar documento")
        botao(app, "Cancelar confirmação").click().run()
        assert not app.exception
        enviar.assert_not_called()
        assert app.text_input[0].value == "Paciente conferido"
        assert not any(b.label == "Confirmar e salvar decisão" for b in app.button)


def test_atualizacao_da_pendencia_invalida_confirmacao():
    fila = [deepcopy(DOCUMENTO)]
    with patch("presentation.web.api_client.consultar", side_effect=lambda caminho: fila if caminho == "filas/auditoria" else []), patch("presentation.web.api_client.enviar") as enviar:
        app = iniciar()
        preparar(app)
        fila[0]["execucao_id"] = "exec-2"
        app.run()
        assert not app.exception
        assert not any(b.label == "Confirmar e salvar decisão" for b in app.button)
        enviar.assert_not_called()


def test_retomada_de_homologacao_na_interface():
    pendentes = [{
        "documento_id": DOCUMENTO["documento_id"],
        "origem_oci_path": DOCUMENTO["armazenamento_oci"]["caminho_objeto"],
    }]
    payload = deepcopy(pendentes[0])

    def retomar(*args):
        pendentes.clear()
        return {"status": "sucesso"}

    with (
        patch("presentation.web.api_client.consultar", side_effect=lambda caminho: pendentes if caminho == "homologacoes/pendentes" else []),
        patch("presentation.web.api_client.enviar", side_effect=retomar) as enviar,
    ):
        app = iniciar()
        assert not app.exception
        botao(app, "Retomar homologação").click().run()
        assert not app.exception
        enviar.assert_called_once_with("homologacoes/retomar", payload)
        assert not any(b.label == "Retomar homologação" for b in app.button)
