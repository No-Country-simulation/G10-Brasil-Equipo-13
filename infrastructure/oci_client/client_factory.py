"""
Fábrica de Injeção de Dependências (Client Factory)
"""

from functools import lru_cache

from config.settings import settings
from application.use_cases.processar_triagem import ProcessarTriagemUseCase
from infrastructure.adapters.gemini_llm_adapter import GeminiLLMAdapter
from infrastructure.oci_client.storage_factory import get_storage_adapter
from infrastructure.adapters.webhook_notifier import WebhookNotifierAdapter

@lru_cache()
def get_triagem_use_case() -> ProcessarTriagemUseCase:
    """
    Constrói a instância singleton do ProcessarTriagemUseCase.
    O ambiente de armazenamento é selecionado pela fábrica de infraestrutura.
    """
    if settings.APP_MODE == "presentation" and not settings.PRESENTATION_USE_LLM:
        from infrastructure.adapters.presentation_llm_adapter import PresentationLLMAdapter
        llm_adapter = PresentationLLMAdapter()
    else:
        llm_adapter = GeminiLLMAdapter(
            api_key=settings.GEMINI_API_KEY, model_name=settings.GEMINI_MODEL_NAME,
            timeout_ms=settings.GEMINI_TIMEOUT_MS, max_attempts=settings.GEMINI_MAX_ATTEMPTS,
        )
    storage_adapter = get_storage_adapter()
    notifier_adapter = WebhookNotifierAdapter(
        webhook_url="" if settings.APP_MODE == "presentation" else settings.WEBHOOK_URL,
        webhook_token=settings.WEBHOOK_TOKEN.get_secret_value(),
    )

    return ProcessarTriagemUseCase(
        llm=llm_adapter,
        storage=storage_adapter,
        notifier=notifier_adapter,
        bucket_name=settings.OCI_BUCKET_NAME,
    )
