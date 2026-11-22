from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from streamlit.testing.v1 import AppTest

from config.settings import settings
from infrastructure.adapters.memory_storage_adapter import MemoryStorageAdapter
from infrastructure.oci_client.client_factory import get_triagem_use_case
from presentation.api.main import app

TOKEN = "credencial-sintetica-para-testes-00000000"
SECRETS = {"auth": {"redirect_uri": "http://localhost:8501/oauth2callback", "cookie_secret": "apenas-testes", "google": {"client_id": "teste", "client_secret": "teste", "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration"}}}
INTEGRACOES = {"armazenamento": {"modo": "simulado", "bucket": "teste"}, "ia": {"provedor": "Gemini", "conexao": "não verificada"}, "alertas": {"modo": "somente_log", "entrega": "não verificada"}}
ENTRADA = Path(__file__).resolve().parents[2] / "presentation/web/app.py"


class Usuario(dict):
    def __init__(self, logado, **claims):
        super().__init__(claims)
        self.is_logged_in = logado


@pytest.fixture
def ambiente_auth(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_PROVIDER", "google")
    monkeypatch.setenv("AUTH_ALLOWED_EMAILS", "colaborador@example.com")
    monkeypatch.setenv("MEDIFLOW_API_TOKEN", TOKEN)


def test_api_protege_consultas_upload_homologacao_e_documentacao(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "MEDIFLOW_API_TOKEN", SecretStr(TOKEN))
    client = TestClient(app)
    for rota in ("/triagem/historico", "/triagem/original?caminho=recebidos/teste.txt", "/triagem/filas/processamento", "/triagem/integracoes", "/docs", "/openapi.json", "/health/ready"):
        assert client.get(rota).status_code == 401
    for rota in ("/triagem", "/triagem/upload", "/triagem/homologar", "/triagem/reprocessar"):
        assert client.post(rota, json={}).status_code == 401
    assert client.get("/health").status_code == 200
    assert client.get("/triagem/historico", headers={"Authorization": "Bearer invalido"}).status_code == 401
    use_case = SimpleNamespace(storage=MemoryStorageAdapter(), bucket_name="teste")
    app.dependency_overrides[get_triagem_use_case] = lambda: use_case
    try:
        assert client.get("/triagem/historico", headers={"Authorization": "Bearer " + TOKEN}).json() == []
    finally:
        app.dependency_overrides.clear()


def test_api_falha_fechada_sem_credencial(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "MEDIFLOW_API_TOKEN", SecretStr(""))
    assert TestClient(app).get("/triagem/historico").status_code == 503


def test_login_nativo_antes_de_consultar_documentos(ambiente_auth):
    with patch("streamlit.user", Usuario(False)), patch("streamlit.secrets", SECRETS), patch("streamlit.login") as login, patch("presentation.web.api_client.consultar") as consultar:
        painel = AppTest.from_file(ENTRADA, default_timeout=30).run()
        assert not painel.exception and not painel.metric
        consultar.assert_not_called()
        next(b for b in painel.button if b.label == "Continuar com Google").click().run()
        login.assert_called_once_with("google")
        consultar.assert_not_called()


@pytest.mark.parametrize("usuario", [Usuario(True, email="estranho@example.com", email_verified=True), Usuario(True, email="colaborador@example.com", email_verified=False)])
def test_identidade_sem_autorizacao_nao_consulta_dados(ambiente_auth, usuario):
    with patch("streamlit.user", usuario), patch("streamlit.secrets", SECRETS), patch("presentation.web.api_client.consultar") as consultar:
        painel = AppTest.from_file(ENTRADA, default_timeout=30).run()
        assert not painel.exception
        assert any("não possui acesso" in e.value for e in painel.error)
        consultar.assert_not_called()


def test_usuario_autorizado_acessa_e_sai_limpando_sessao(ambiente_auth):
    with patch("streamlit.user", Usuario(True, email="Colaborador@example.com", email_verified=True)), patch("streamlit.secrets", SECRETS), patch("streamlit.logout") as logout, patch("presentation.web.api_client.consultar", side_effect=lambda caminho: INTEGRACOES if caminho == "integracoes" else []):
        painel = AppTest.from_file(ENTRADA, default_timeout=30).run()
        assert not painel.exception and painel.metric
        painel.session_state.resultado_triagem = {"documento_id": "PRIVADO"}
        next(b for b in painel.button if b.label == "Sair").click().run()
        logout.assert_called_once()
        assert "resultado_triagem" not in painel.session_state


def test_auth_incompleta_nao_volta_para_acesso_anonimo(ambiente_auth):
    with patch("streamlit.user", Usuario(False)), patch("streamlit.secrets", {}), patch("presentation.web.api_client.consultar") as consultar:
        painel = AppTest.from_file(ENTRADA, default_timeout=30).run()
        assert not painel.exception and painel.error
        assert not any(b.label == "Continuar com Google" for b in painel.button)
        consultar.assert_not_called()


def test_token_de_servico_incluido_em_todas_as_chamadas(monkeypatch):
    from presentation.web import api_client
    monkeypatch.setenv("MEDIFLOW_API_TOKEN", TOKEN)
    with patch("requests.get") as get, patch("requests.post") as post:
        api_client.consultar("historico")
        api_client.obter_original("recebidos/teste.txt")
        api_client.enviar("homologar", {})
        for chamada in get.call_args_list + post.call_args_list:
            assert chamada.kwargs["headers"]["Authorization"] == "Bearer " + TOKEN
