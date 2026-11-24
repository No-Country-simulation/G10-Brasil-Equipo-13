"""Regressões da Issue #33: padronização de erros inesperados HTTP 500 na API."""

import logging
import re
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from infrastructure.adapters.memory_storage_adapter import MemoryStorageAdapter
from infrastructure.oci_client.client_factory import get_triagem_use_case
from presentation.api.main import app


@pytest.fixture
def client_com_falha_inesperada():
    storage = MemoryStorageAdapter()
    storage.salvar_arquivo("teste", "recebidos/DOC-33.txt", b"conteudo sintetico")
    storage.salvar_json(
        "teste",
        "processados/rotina/DOC-33.json",
        {
            "documento_id": "DOC-33",
            "tipo_arquivo": "TEXTO",
            "armazenamento_oci": {"caminho_documento_bruto": "recebidos/DOC-33.txt"},
        },
    )
    use_case = Mock()
    use_case.bucket_name = "teste"
    use_case.storage = storage
    use_case.executar.side_effect = RuntimeError(
        "detalhe-interno-sigiloso dsn=secret paciente=DadosSensiveis"
    )
    app.dependency_overrides[get_triagem_use_case] = lambda: use_case
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "metodo_chamada",
    [
        lambda c: c.post(
            "/triagem",
            json={
                "documento_id": "DOC-33-JSON",
                "tipo_arquivo": "TEXTO",
                "documento_texto": "Documento sintético sigiloso-payload",
                "canal_origem": "Teste",
            },
        ),
        lambda c: c.post(
            "/triagem/upload",
            data={"documento_id": "DOC-33-UP", "canal_origem": "Teste"},
            files={"arquivo": ("caso.txt", b"texto sintetico", "text/plain")},
        ),
        lambda c: c.post(
            "/triagem/reprocessar",
            json={
                "documento_id": "DOC-33",
                "origem_oci_path": "processados/rotina/DOC-33.json",
                "canal_origem": "Teste",
            },
        ),
    ],
)
def test_erro_inesperado_retorna_mensagem_generica_e_referencia_no_log(
    client_com_falha_inesperada, caplog, metodo_chamada
):
    caplog.set_level(logging.ERROR, logger="MediFlowAuditoria")
    resposta = metodo_chamada(client_com_falha_inesperada)

    assert resposta.status_code == 500
    detalhe = resposta.json()["detail"]
    assert "detalhe-interno-sigiloso" not in detalhe
    assert "dsn=" not in detalhe
    assert "DadosSensiveis" not in detalhe
    assert "sigiloso-payload" not in detalhe

    match = re.search(r"referência ([0-9a-f]{12})", detalhe)
    assert match is not None
    referencia = match.group(1)

    logs_auditoria = [r for r in caplog.records if r.name == "MediFlowAuditoria"]
    assert logs_auditoria
    assert any(referencia in r.getMessage() and "RuntimeError" in r.getMessage() for r in logs_auditoria)
    assert "sigiloso-payload" not in caplog.text
