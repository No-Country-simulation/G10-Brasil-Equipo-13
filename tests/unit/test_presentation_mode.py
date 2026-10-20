import base64
from unittest.mock import patch
import pytest
from pydantic import ValidationError
from config.settings import Settings
from application.dtos.input_request import TriagemRequestDTO
from infrastructure.adapters.presentation_llm_adapter import EXEMPLOS, PresentationLLMAdapter
from infrastructure.oci_client import client_factory, storage_factory
from infrastructure.diagnostico import diagnosticar


def test_apresentacao_rejeita_storage_permanente():
    with pytest.raises(ValidationError, match="exige STORAGE_MODE=memory"):
        Settings(_env_file=None, APP_MODE="presentation", STORAGE_MODE="oci")


def test_simulacao_fluxo_real_sem_gemini_ou_webhook():
    cfg = Settings(_env_file=None, APP_MODE="presentation", STORAGE_MODE="memory", GEMINI_API_KEY="", WEBHOOK_URL="https://example.invalid/alert")
    client_factory.get_triagem_use_case.cache_clear()
    storage_factory.get_storage_adapter.cache_clear()
    try:
        with patch.object(client_factory, "settings", cfg), patch.object(storage_factory, "settings", cfg), patch("infrastructure.diagnostico.settings", cfg), patch.object(client_factory, "GeminiLLMAdapter", side_effect=AssertionError("LLM não deve iniciar")), patch("requests.post", side_effect=AssertionError("Webhook não deve sair")):
            caso = client_factory.get_triagem_use_case()
            assert caso.notifier.webhook_url is None
            resultados = {}
            for nome in ("rotina", "urgencia", "revisao"):
                dto = TriagemRequestDTO(documento_id="DEMO-" + nome, tipo_arquivo="TEXTO", canal_origem="Apresentacao", arquivo_base64=base64.b64encode((EXEMPLOS / f"{nome}.txt").read_bytes()).decode())
                resultados[nome] = caso.executar(dto)
            assert not resultados["rotina"].decisao_roteamento.requer_auditoria_humana
            assert resultados["urgencia"].classificacao.nivel_prioridade == "Urgente"
            assert resultados["revisao"].decisao_roteamento.requer_auditoria_humana
            assert all(r.armazenamento_oci.status_backup == "sucesso" for r in resultados.values())
            assert not any(i["estado"] == "erro" for i in diagnosticar()["itens"])
    finally:
        client_factory.get_triagem_use_case.cache_clear()
        storage_factory.get_storage_adapter.cache_clear()


def test_exemplo_urgencia_sem_crm_reconhecido():
    bruto = (EXEMPLOS / "urgencia_sem_crm.txt").read_bytes()
    resultado = PresentationLLMAdapter().processar_documento(base64.b64encode(bruto).decode(), "TEXTO")
    assert resultado["achado_critico"] is True
    assert resultado["nivel_prioridade"] == "Urgente"
    assert resultado["medico_solicitante"]["crm"] is None
    assert resultado["paciente"]["nome"]
    assert resultado["score_confianca"] >= 0.85


def test_desconhecido_nao_recebe_resultado_ficticio():
    from domain.exceptions import FalhaExtracaoIA
    with pytest.raises(FalhaExtracaoIA, match="use um dos três arquivos"):
        PresentationLLMAdapter().processar_documento("rotina.txt", "TEXTO")


def test_llm_real_explicita_sem_fallback():
    cfg = Settings(_env_file=None, APP_MODE="presentation", PRESENTATION_USE_LLM=True, STORAGE_MODE="memory", GEMINI_API_KEY="teste")
    client_factory.get_triagem_use_case.cache_clear()
    try:
        with patch.object(client_factory, "settings", cfg), patch.object(client_factory, "GeminiLLMAdapter", side_effect=RuntimeError("Falha real")) as gemini:
            with pytest.raises(RuntimeError, match="Falha real"):
                client_factory.get_triagem_use_case()
            gemini.assert_called_once()
    finally:
        client_factory.get_triagem_use_case.cache_clear()


def test_readiness_simulado_sem_chave():
    import asyncio
    from fastapi import Response
    from presentation.api.routers import health_router
    cfg = Settings(_env_file=None, APP_MODE="presentation", STORAGE_MODE="memory", GEMINI_API_KEY="")
    from infrastructure.adapters.memory_storage_adapter import MemoryStorageAdapter
    with patch.object(health_router, "settings", cfg), patch.object(health_router, "get_storage_adapter", return_value=MemoryStorageAdapter()):
        resposta = Response()
        resultado = asyncio.run(health_router.readiness_check(resposta))
        assert resposta.status_code == 200
        assert resultado.dependencias["llm_service"]["provedor"] == "Simulação de apresentação"
