"""Executar com RUN_OCI_EMULATOR_TESTS=1; usa SDK OCI real e container local."""
import os
from uuid import uuid4

import pytest
from application.use_cases.acompanhar_fluxo import chave_fluxo
from application.use_cases.identidade_documento import chave_cadastro
from fastapi.testclient import TestClient
from unittest.mock import Mock

from application.use_cases.processar_triagem import ProcessarTriagemUseCase
from infrastructure.adapters.oci_storage_adapter import OCIStorageAdapter
from infrastructure.oci_client.storage_factory import criar_config_emulador, LOCAL_TENANCY
from infrastructure.oci_client.client_factory import get_triagem_use_case
from presentation.api.main import app

pytestmark = pytest.mark.skipif(os.getenv("RUN_OCI_EMULATOR_TESTS") != "1", reason="Requer emulador OCI local ativo.")


def test_sdk_e_fluxo_auditoria_via_api():
    endpoint = os.getenv("OCI_SERVICE_ENDPOINT", "http://localhost:4599")
    storage = OCIStorageAdapter(criar_config_emulador(endpoint), "", endpoint)
    storage.namespace = storage.client.get_namespace().data
    bucket = "mediflow-testes-integracao"
    storage.garantir_bucket(bucket, LOCAL_TENANCY)
    documento_id = "TESTE-" + uuid4().hex
    origem = f"auditoria_humana/{documento_id}.json"
    destino = f"processados/rotina/{documento_id}.json"
    bruto = f"recebidos/{documento_id}.txt"
    doc = {}
    dados = {"tipo_documento": "Receituário", "especialidade": "Clínica Geral", "nivel_prioridade": "Rotina", "score_confianca": .4, "paciente": {"nome": None}, "medico_solicitante": {"crm": None}, "medicamentos": [], "achado_critico": False}
    llm = Mock()
    llm.processar_documento.return_value = dados
    caso = ProcessarTriagemUseCase(llm, storage, Mock(), bucket)
    app.dependency_overrides[get_triagem_use_case] = lambda: caso
    try:
        client = TestClient(app)
        resposta = client.post("/triagem", json={"documento_id": documento_id, "tipo_arquivo": "TEXTO", "documento_texto": "Documento sintético para teste local.", "canal_origem": "Teste"})
        assert resposta.status_code == 200
        doc = resposta.json()
        origem = doc["armazenamento_oci"]["caminho_objeto"]
        bruto = doc["armazenamento_oci"]["caminho_documento_bruto"]
        assert resposta.json()["decisao_roteamento"]["requer_auditoria_humana"]
        assert storage.obter_arquivo(bucket, bruto) == b"Documento sint\xc3\xa9tico para teste local."
        assert origem in storage.listar_objetos_por_prefixo(bucket, "auditoria_humana/")
        fluxo = next(d for d in client.get("/triagem/filas/processamento").json() if d["documento_id"] == documento_id)
        assert fluxo["etapa"] == "revisao_humana"
        assert [e["etapa"] for e in fluxo["eventos"]] == ["recebidos", "em_analise", "revisao_humana"]
        assert client.get("/triagem/original", params={"caminho": bruto}).status_code == 200
        homologacao = client.post("/triagem/homologar", json={"documento_id": documento_id, "origem_oci_path": origem, "paciente_nome": "Paciente Fictício", "crm_retificado": "123456-SP", "diagnostico": "Exemplo sintético", "cid_homologado": "Z00", "destino_aprovado": "Farmacia_Hospitalar", "parecer_auditor": "Conferência de teste", "decisao": "aprovar"})
        assert homologacao.status_code == 200
        destino = homologacao.json()["caminho_novo_oci"]
        assert storage.obter_json(bucket, origem) is None
        assert storage.obter_json(bucket, destino)["dados_extraidos"]["paciente"]["nome"] == "Paciente Fictício"
        assert any(d["documento_id"] == documento_id for d in client.get("/triagem/historico").json())
        fluxo = next(d for d in client.get("/triagem/filas/processamento").json() if d["documento_id"] == documento_id)
        assert fluxo["etapa"] == "encaminhados"
        assert fluxo["eventos"][-1]["etapa"] == "encaminhados"
    finally:
        app.dependency_overrides.clear()
        for chave in (bruto, origem, destino, chave_fluxo(documento_id, doc.get("execucao_id")), chave_cadastro(documento_id)):
            try:
                storage.client.delete_object(storage.namespace, bucket, chave)
            except Exception:
                pass
