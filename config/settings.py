import os
from typing import Literal
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_ENV: Literal["local", "cloud"] = "local"
    APP_MODE: Literal["operational", "presentation"] = "operational"
    PRESENTATION_USE_LLM: bool = False
    AUTH_ENABLED: bool = False
    MEDIFLOW_API_TOKEN: SecretStr = SecretStr("")
    AUTH_ALLOWED_EMAILS: str = ""
    AUTH_PROVIDER: str = "google"
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL_NAME: str = Field(default="gemini-3.5-flash", min_length=1)
    GEMINI_TIMEOUT_MS: int = Field(default=20000, ge=1000, le=60000)
    GEMINI_MAX_ATTEMPTS: int = Field(default=3, ge=1, le=3)
    OCI_CONFIG_FILE: str = os.getenv("OCI_CONFIG_FILE", "~/.oci/config")
    OCI_CONFIG_PROFILE: str = os.getenv("OCI_CONFIG_PROFILE", "DEFAULT")
    # Aceita no .env os caminhos usados apenas pelo Compose; o SDK usa OCI_CONFIG_FILE.
    OCI_CONFIG_HOST_FILE: str = ""
    OCI_KEY_HOST_FILE: str = ""
    STORAGE_MODE: Literal["memory", "emulator", "oci"] = "memory"
    OCI_SERVICE_ENDPOINT: str = "http://localhost:4599"
    MEDIFLOW_RESERVAS_DB: str = ""
    OCI_NAMESPACE: str = os.getenv("OCI_NAMESPACE", "mi-tenancy-namespace")
    OCI_BUCKET_NAME: str = os.getenv("OCI_BUCKET_NAME", "mediflow-documentos-clinicos")

    WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "")
    WEBHOOK_TOKEN: SecretStr = SecretStr("")

    model_config = SettingsConfigDict(env_file=".env")

    @model_validator(mode="after")
    def validar_apresentacao(self):
        if self.APP_MODE == "presentation" and self.STORAGE_MODE != "memory":
            raise ValueError("Modo apresentação exige STORAGE_MODE=memory.")
        return self


settings = Settings()


