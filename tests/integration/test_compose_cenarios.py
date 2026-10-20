"""HTTP real contra API Compose; Gemini substituído apenas na entrada de testes."""
import os
from uuid import uuid4

import pytest
import requests
from oci.exceptions import ServiceError

from infrastructure.adapters.presentation_llm_adapter import EXEMPLOS
from infrastructure.adapters.oci_storage_adapter import OCIStorageAdapter
from infrastructure.oci_client.storage_factory import criar_config_emulador
from application.use_cases.acompanhar_fluxo import chave_fluxo

pytestmark = pytest.mark.skipif(os.getenv("RUN_COMPOSE_TESTS") != "1", reason="Requer Compose de testes ativo")


@pytest.mark.parametrize("cenario,destino,prefixo,etapa", [
    ("rotina", "Farmacia_Hospitalar", "processados/rotina/", "encaminhados"),
    ("urgencia", "Fila_Emergencia_Medica", "processados/urgentes/", "encaminhados"),
    ("revisao", "Fila_Revisao_Humana", "auditoria_humana/", "revisao_humana"),
    ("urgencia_sem_crm", "Fila_Emergencia_Medica", "auditoria_humana/", "revisao_humana"),
])
def test_cenario_http_compose_oci(cenario, destino, prefixo, etapa):
    api = os.getenv("COMPOSE_TEST_API_URL", "http://localhost:8001/triagem")
    endpoint = os.getenv("OCI_SERVICE_ENDPOINT", "http://localhost:4599")
    storage = OCIStorageAdapter(criar_config_emulador(endpoint), "", endpoint)
    storage.namespace = storage.client.get_namespace().data
    bucket = "mediflow-testes-compose"
    doc_id = "COMPOSE-" + uuid4().hex
    bruto = (EXEMPLOS / f"{cenario}.txt").read_bytes()
    path = prefixo + doc_id + ".json"
    try:
        resposta = requests.post(api + "/upload", data={"documento_id": doc_id, "canal_origem": "Teste Compose"}, files={"arquivo": (cenario + ".txt", bruto, "text/plain")}, timeout=30)
        assert resposta.status_code == 200, resposta.text
        doc = resposta.json()
        assert doc["armazenamento_oci"]["status_backup"] == "sucesso"
        assert doc["armazenamento_oci"]["caminho_objeto"] == path
        decisao = doc["decisao_roteamento"]
        assert decisao["destino_principal"] == destino
        assert decisao["requer_auditoria_humana"] is (cenario in ("revisao", "urgencia_sem_crm"))
        assert storage.obter_arquivo(bucket, f"recebidos/{doc_id}.txt") == bruto
        assert storage.obter_json(bucket, path)["decisao_roteamento"] == decisao
        filas = {"revisao": ["auditoria"], "urgencia": ["urgencias"],
                 "urgencia_sem_crm": ["urgencias", "auditoria"]}.get(cenario, [])
        for fila in filas:
            r = requests.get(api + "/filas/" + fila, timeout=10)
            r.raise_for_status()
            assert any(d["documento_id"] == doc_id for d in r.json())
        r = requests.get(api + "/filas/processamento", timeout=10)
        r.raise_for_status()
        assert next(d for d in r.json() if d["documento_id"] == doc_id)["etapa"] == etapa
        if cenario.startswith("urgencia"):
            assert decisao["notificacao_gerada"]["canal"] == "Alerta_Plantao_Medico"
        adicionais = [n["canal"] for n in decisao["notificacoes_adicionais"]]
        assert adicionais == (["Email_Auditoria"] if cenario == "urgencia_sem_crm" else [])
    finally:
        for chave in (f"recebidos/{doc_id}.txt", path, chave_fluxo(doc_id)):
            try:
                storage.client.delete_object(storage.namespace, bucket, chave)
            except ServiceError as exc:
                if exc.status != 404:
                    raise
