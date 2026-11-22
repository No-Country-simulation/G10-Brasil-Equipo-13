"""Webhook interno HTTP com entrega SMTP autenticada e TLS obrigatório."""
import logging
import smtplib
import ssl
from email.message import EmailMessage
from secrets import compare_digest
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class EmailSettings(BaseSettings):
    WEBHOOK_TOKEN: SecretStr = SecretStr("")
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = Field(default=587, ge=1, le=65535)
    SMTP_SECURITY: Literal["starttls", "ssl"] = "starttls"
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: SecretStr = SecretStr("")
    SMTP_FROM: str = ""
    SMTP_TO: str = ""
    SMTP_TIMEOUT: float = Field(default=3, gt=0, le=30)
    SMTP_CA_FILE: str = ""
    model_config = SettingsConfigDict(extra="ignore")

    def pronta(self):
        enderecos = (self.SMTP_FROM, self.SMTP_TO)
        return (
            len(self.WEBHOOK_TOKEN.get_secret_value()) >= 32
            and bool(self.SMTP_HOST and self.SMTP_USERNAME and self.SMTP_PASSWORD.get_secret_value())
            and all("@" in e and not any(c in e for c in "\r\n,;") for e in enderecos)
        )


def get_settings():
    return EmailSettings()


class Alerta(BaseModel):
    canal: Literal["Alerta_Plantao_Medico", "Email_Auditoria"]
    mensagem: str = Field(min_length=1, max_length=20000)


def autenticar(
    authorization: str = Header(default=""),
    cfg: EmailSettings = Depends(get_settings),
):
    token = cfg.WEBHOOK_TOKEN.get_secret_value()
    if len(token) < 32:
        raise HTTPException(503, "Credencial do notificador não configurada.")
    if not compare_digest(authorization.encode(), ("Bearer " + token).encode()):
        raise HTTPException(401, "Credencial inválida.")


def enviar_email(cfg, alerta):
    email = EmailMessage()
    email["From"] = cfg.SMTP_FROM
    email["To"] = cfg.SMTP_TO
    assunto = "Urgência" if alerta.canal == "Alerta_Plantao_Medico" else "Revisão humana"
    email["Subject"] = "MediFlow — " + assunto
    email.set_content(alerta.mensagem)
    contexto = ssl.create_default_context()
    if cfg.SMTP_CA_FILE:
        contexto.load_verify_locations(cafile=cfg.SMTP_CA_FILE)
    if cfg.SMTP_SECURITY == "ssl":
        cliente = smtplib.SMTP_SSL(cfg.SMTP_HOST, cfg.SMTP_PORT, timeout=cfg.SMTP_TIMEOUT, context=contexto)
    else:
        cliente = smtplib.SMTP(cfg.SMTP_HOST, cfg.SMTP_PORT, timeout=cfg.SMTP_TIMEOUT)
    with cliente as smtp:
        if cfg.SMTP_SECURITY == "starttls":
            smtp.ehlo()
            smtp.starttls(context=contexto)
            smtp.ehlo()
        smtp.login(cfg.SMTP_USERNAME, cfg.SMTP_PASSWORD.get_secret_value())
        recusados = smtp.send_message(email)
        if recusados:
            raise smtplib.SMTPRecipientsRefused(recusados)


app = FastAPI(title="MediFlow — Notificador de e-mail", docs_url=None, redoc_url=None)


@app.get("/health")
def health(cfg: EmailSettings = Depends(get_settings)):
    if not cfg.pronta():
        raise HTTPException(503, "Configure remetente, destinatário, senha SMTP e token.")
    return {"status": "configurado", "smtp": "nao_verificado"}


@app.post("/alertas", dependencies=[Depends(autenticar)])
def receber_alerta(alerta: Alerta, cfg: EmailSettings = Depends(get_settings)):
    if not cfg.pronta():
        raise HTTPException(503, "Envio de e-mail não configurado.")
    try:
        enviar_email(cfg, alerta)
    except Exception:
        logger.warning("Falha na entrega SMTP do alerta.")
        raise HTTPException(502, "O servidor SMTP não confirmou o envio.") from None
    return {"status": "aceito_pelo_smtp"}
