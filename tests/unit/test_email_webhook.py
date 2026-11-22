import smtplib
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from infrastructure.notifications import email_webhook as email
from infrastructure.adapters.webhook_notifier import WebhookNotifierAdapter


@pytest.fixture
def contexto():
    cfg = email.EmailSettings(
        _env_file=None, WEBHOOK_TOKEN="t" * 40,
        SMTP_USERNAME="remetente@example.invalid", SMTP_PASSWORD="senha-ficticia",
        SMTP_FROM="remetente@example.invalid", SMTP_TO="destino@example.invalid",
    )
    email.app.dependency_overrides[email.get_settings] = lambda: cfg
    try:
        with TestClient(email.app) as client:
            yield client, cfg
    finally:
        email.app.dependency_overrides.clear()


@pytest.mark.parametrize("canal", ["Alerta_Plantao_Medico", "Email_Auditoria"])
def test_alertas_entregues_ao_smtp_com_tls(contexto, canal):
    client, cfg = contexto
    with patch.object(email.smtplib, "SMTP") as factory:
        smtp = factory.return_value.__enter__.return_value
        smtp.send_message.return_value = {}
        resposta = client.post("/alertas", headers={"Authorization": "Bearer " + "t" * 40},
                               json={"canal": canal, "mensagem": "Alerta sintético", "text": "ignorar"})
        assert resposta.status_code == 200
        assert resposta.json()["status"] == "aceito_pelo_smtp"
        smtp.starttls.assert_called_once()
        smtp.login.assert_called_once_with(cfg.SMTP_USERNAME, "senha-ficticia")
        enviado = smtp.send_message.call_args.args[0]
        assert enviado["To"] == cfg.SMTP_TO
        assert "Alerta sintético" in enviado.get_content()


@pytest.mark.parametrize("token", ["", "Bearer errado"])
def test_sem_autorizacao_nao_envia(contexto, token):
    client, _ = contexto
    with patch.object(email, "enviar_email") as envio:
        assert client.post("/alertas", headers={"Authorization": token},
                           json={"canal": "Email_Auditoria", "mensagem": "Teste"}).status_code == 401
        envio.assert_not_called()


def test_configuracao_incompleta_nao_simula_envio(contexto):
    client, cfg = contexto
    cfg.SMTP_PASSWORD = email.SecretStr("")
    assert client.get("/health").status_code == 503
    with patch.object(email, "enviar_email") as envio:
        assert client.post("/alertas", headers={"Authorization": "Bearer " + "t" * 40},
                           json={"canal": "Email_Auditoria", "mensagem": "Teste"}).status_code == 503
        envio.assert_not_called()


def test_falha_smtp_nao_vaza_segredos(contexto):
    client, _ = contexto
    with patch.object(email, "enviar_email", side_effect=smtplib.SMTPAuthenticationError(535, b"segredo")):
        resp = client.post("/alertas", headers={"Authorization": "Bearer " + "t" * 40},
                           json={"canal": "Email_Auditoria", "mensagem": "Teste"})
    assert resp.status_code == 502
    assert "segredo" not in resp.text


def test_canal_desconhecido_rejeitado(contexto):
    client, _ = contexto
    assert client.post("/alertas", headers={"Authorization": "Bearer " + "t" * 40},
                       json={"canal": "outro", "mensagem": "Teste"}).status_code == 422


def test_recusa_destinatario_nao_confirma_envio(contexto):
    _, cfg = contexto
    with patch.object(email.smtplib, "SMTP") as factory:
        factory.return_value.__enter__.return_value.send_message.return_value = {cfg.SMTP_TO: (550, b"recusado")}
        with pytest.raises(smtplib.SMTPRecipientsRefused):
            email.enviar_email(cfg, email.Alerta(canal="Email_Auditoria", mensagem="Teste"))


def test_tls_implicito(contexto):
    _, cfg = contexto
    cfg.SMTP_SECURITY, cfg.SMTP_PORT = "ssl", 465
    with patch.object(email.smtplib, "SMTP_SSL") as factory:
        smtp = factory.return_value.__enter__.return_value
        smtp.send_message.return_value = {}
        email.enviar_email(cfg, email.Alerta(canal="Email_Auditoria", mensagem="Teste"))
        smtp.starttls.assert_not_called()
        smtp.login.assert_called_once()


def test_cliente_webhook_envia_token_e_mantem_payload():
    with patch("infrastructure.adapters.webhook_notifier.requests.post", return_value=Mock(status_code=200)) as post:
        assert WebhookNotifierAdapter("http://notificador:8080/alertas", webhook_token="teste").enviar_alerta_urgencia("Email_Auditoria", "Teste")
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer teste"


def test_cliente_webhook_antigo_sem_token():
    with patch("infrastructure.adapters.webhook_notifier.requests.post", return_value=Mock(status_code=200)) as post:
        assert WebhookNotifierAdapter("http://example.invalid").enviar_alerta_urgencia("Email_Auditoria", "Teste")
    assert "Authorization" not in post.call_args.kwargs["headers"]


def test_ca_adicional_invalida_impede_smtp(contexto):
    _, cfg = contexto
    cfg.SMTP_CA_FILE = "/arquivo-ca-inexistente.pem"
    with patch.object(email.smtplib, "SMTP") as smtp:
        with pytest.raises(OSError):
            email.enviar_email(cfg, email.Alerta(canal="Email_Auditoria", mensagem="Teste"))
        smtp.assert_not_called()
