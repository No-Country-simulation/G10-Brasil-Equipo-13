"""Regressão da issue #27: origem preservada na resposta e no relatório."""
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from application.dtos.output_response import TriagemResponseDTO
from application.use_cases.processar_triagem import ProcessarTriagemUseCase
from infrastructure.adapters.memory_storage_adapter import MemoryStorageAdapter
from infrastructure.adapters.presentation_llm_adapter import (
    EXEMPLOS,
    PresentationLLMAdapter,
    resultado_exemplo,
)
from infrastructure.oci_client.client_factory import get_triagem_use_case
from presentation.api.main import app


@pytest.fixture(params=["operational", "presentation"])
def contexto(request):
    # Ambos os modos compartilham o caso de uso. Em operação, simula somente a LLM.
    llm = PresentationLLMAdapter() if request.param == "presentation" else Mock()
    if request.param == "operational":
        llm.processar_documento.return_value = resultado_exemplo("rotina")
    caso = ProcessarTriagemUseCase(llm, MemoryStorageAdapter(), Mock(), "teste")
    app.dependency_overrides[get_triagem_use_case] = lambda: caso
    try:
        with TestClient(app) as client:
            yield client, caso
    finally:
        app.dependency_overrides.clear()


def enviar(client, canal, entrada):
    texto = (EXEMPLOS / "rotina.txt").read_text(encoding="utf-8")
    if entrada == "upload":
        return client.post(
            "/triagem/upload",
            data={"documento_id": "ORIGEM", "canal_origem": canal},
            files={"arquivo": ("rotina.txt", texto.encode("utf-8"), "text/plain")},
        )
    return client.post("/triagem", json={
        "documento_id": "ORIGEM", "canal_origem": canal,
        "tipo_arquivo": "TEXTO", "documento_texto": texto,
    })


@pytest.mark.parametrize("canal", ["Pronto_Socorro", "Ambulatorio", "Recepcao"])
@pytest.mark.parametrize("entrada", ["json", "upload"])
def test_preserva_canal_na_resposta_relatorio_e_historico(contexto, canal, entrada):
    client, caso = contexto
    resposta = enviar(client, canal, entrada)
    assert resposta.status_code == 200
    doc = resposta.json()
    assert doc.get("canal_origem") == canal
    caminho = doc["armazenamento_oci"]["caminho_objeto"]
    assert caso.storage.obter_json("teste", caminho)["canal_origem"] == canal
    assert client.get("/triagem/historico").json()[0]["canal_origem"] == canal
    assert client.get("/triagem/filas/processamento").json()[0]["canal_origem"] == canal


@pytest.mark.parametrize("origem", ["ausente", None])
def test_registro_antigo_sem_origem_continua_valido(contexto, origem):
    client, caso = contexto
    resposta = enviar(client, "Recepcao", "json")
    assert resposta.status_code == 200
    antigo = resposta.json()
    antigo.pop("canal_origem", None)
    if origem is None:
        antigo["canal_origem"] = None
    validado = TriagemResponseDTO.model_validate(antigo)
    assert validado.canal_origem is None
    caminho = antigo["armazenamento_oci"]["caminho_objeto"]
    caso.storage.salvar_json("teste", caminho, antigo)
    historico = client.get("/triagem/historico")
    assert historico.status_code == 200
    assert historico.json()[0].get("canal_origem") is None
