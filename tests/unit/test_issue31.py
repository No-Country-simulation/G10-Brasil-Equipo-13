"""Integridade documental: executar também com RUN_OCI_EMULATOR_TESTS=1."""
import base64
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from application.use_cases.acompanhar_fluxo import consultar_fluxo, chave_fluxo
from application.use_cases.processar_triagem import ProcessarTriagemUseCase
from infrastructure.adapters.memory_storage_adapter import MemoryStorageAdapter
from infrastructure.adapters.presentation_llm_adapter import resultado_exemplo
from infrastructure.oci_client.client_factory import get_triagem_use_case
from presentation.api.main import app


@pytest.fixture(params=["memory", "emulator"])
def contexto(request):
    bucket = "issue31-" + uuid4().hex
    if request.param == "emulator":
        if os.getenv("RUN_OCI_EMULATOR_TESTS") != "1":
            pytest.skip("Requer emulador OCI local")
        from infrastructure.adapters.oci_storage_adapter import OCIStorageAdapter
        from infrastructure.oci_client.storage_factory import criar_config_emulador, LOCAL_TENANCY
        endpoint = os.getenv("OCI_SERVICE_ENDPOINT", "http://localhost:4599")
        storage = OCIStorageAdapter(criar_config_emulador(endpoint), "", endpoint)
        storage.namespace = storage.client.get_namespace().data
        storage.garantir_bucket(bucket, LOCAL_TENANCY)
    else:
        storage = MemoryStorageAdapter()
    llm, notifier = Mock(), Mock()
    llm.processar_documento.return_value = resultado_exemplo("rotina")
    caso = ProcessarTriagemUseCase(llm, storage, notifier, bucket)
    app.dependency_overrides[get_triagem_use_case] = lambda: caso
    try:
        with TestClient(app) as client:
            yield client, caso, llm, notifier
    finally:
        app.dependency_overrides.clear()
        if request.param == "emulator":
            for chave in storage.listar_objetos_por_prefixo(bucket, ""):
                storage.client.delete_object(storage.namespace, bucket, chave)
            storage.client.delete_bucket(storage.namespace, bucket)


def payload(**kwargs):
    return {"documento_id": "001", "tipo_arquivo": "TEXTO", "documento_texto": "Original sintético", "canal_origem": "Recepcao", **kwargs}


def snapshot(caso):
    return {k: caso.storage.obter_arquivo(caso.bucket_name, k) for k in caso.storage.listar_objetos_por_prefixo(caso.bucket_name, "")}


@pytest.mark.parametrize("alteracao", [{}, {"documento_texto": "Outro conteúdo"},
    {"tipo_arquivo": "PDF", "documento_texto": None, "arquivo_base64": base64.b64encode(b"%PDF-sintetico").decode()}])
def test_duplicado_409_sem_efeitos_colaterais(contexto, alteracao):
    client, caso, llm, notifier = contexto
    assert client.post("/triagem", json=payload()).status_code == 200
    antes = snapshot(caso)
    llm.reset_mock(); notifier.reset_mock()
    assert client.post("/triagem", json=payload(**alteracao)).status_code == 409
    assert snapshot(caso) == antes
    llm.processar_documento.assert_not_called()
    notifier.enviar_alerta_urgencia.assert_not_called()
    llm.processar_documento.assert_not_called()
    notifier.enviar_alerta_urgencia.assert_not_called()
    resposta = client.post("/triagem/upload", data={"documento_id": "001", "canal_origem": "Ambulatorio"}, files={"arquivo": ("outro.txt", b"Outro", "text/plain")})
    assert resposta.status_code == 409
    assert snapshot(caso) == antes


def test_concorrencia_uma_criacao_um_409(contexto):
    client, caso, llm, _ = contexto
    barreira = Barrier(2)
    criar = caso.storage.criar_json_exclusivo
    def concorrente(*args, **kwargs):
        barreira.wait(timeout=15)
        return criar(*args, **kwargs)
    with patch.object(caso.storage, "criar_json_exclusivo", side_effect=concorrente):
        with ThreadPoolExecutor(max_workers=2) as pool:
            futuros = [pool.submit(client.post, "/triagem", json=payload()) for _ in range(2)]
            assert sorted(f.result(timeout=30).status_code for f in futuros) == [200, 409]
    assert llm.processar_documento.call_count == 1
    assert len(client.get("/triagem/historico").json()) == 1


def test_reprocessamento_preserva_original_origem_destino_e_historico(contexto):
    client, caso, llm, _ = contexto
    primeiro = client.post("/triagem", json=payload()).json()
    antes = snapshot(caso)
    llm.processar_documento.return_value = resultado_exemplo("urgencia")
    resposta = client.post("/triagem/reprocessar", json={"documento_id": "001", "origem_oci_path": primeiro["armazenamento_oci"]["caminho_objeto"], "canal_origem": "Pronto_Socorro"})
    assert resposta.status_code == 200, resposta.text
    segundo = resposta.json()
    assert primeiro["execucao_id"] != segundo["execucao_id"]
    assert segundo["reprocessamento_de"] == primeiro["armazenamento_oci"]["caminho_objeto"]
    assert segundo["execucao_anterior_id"] == primeiro["execucao_id"]
    assert primeiro["canal_origem"] == "Recepcao" and segundo["canal_origem"] == "Pronto_Socorro"
    assert primeiro["decisao_roteamento"]["destino_principal"] != segundo["decisao_roteamento"]["destino_principal"]
    depois = snapshot(caso)
    assert all(depois[k] == v for k, v in antes.items())
    assert depois[segundo["armazenamento_oci"]["caminho_documento_bruto"]] == b"Original sint\xc3\xa9tico"
    assert len(client.get("/triagem/historico").json()) == 2
    registros = consultar_fluxo(caso.storage, caso.bucket_name)
    assert {r["execucao_id"] for r in registros} == {primeiro["execucao_id"], segundo["execucao_id"]}
    assert all(r["eventos"] for r in registros)


def test_falha_e_nova_instancia_nao_liberam_id(contexto):
    client, caso, llm, _ = contexto
    llm.processar_documento.side_effect = RuntimeError("Falha sintética")
    assert client.post("/triagem", json=payload()).status_code == 500
    antes = snapshot(caso)
    storage_reaberto = caso.storage
    if caso.storage.modo == "oci":
        from infrastructure.adapters.oci_storage_adapter import OCIStorageAdapter
        from infrastructure.oci_client.storage_factory import criar_config_emulador
        endpoint = os.getenv("OCI_SERVICE_ENDPOINT", "http://localhost:4599")
        storage_reaberto = OCIStorageAdapter(criar_config_emulador(endpoint), caso.storage.namespace, endpoint)
    novo = ProcessarTriagemUseCase(llm, storage_reaberto, Mock(), caso.bucket_name)
    app.dependency_overrides[get_triagem_use_case] = lambda: novo
    assert client.post("/triagem", json=payload()).status_code == 409
    assert snapshot(caso) == antes
    llm.processar_documento.side_effect = None
    fluxo = consultar_fluxo(caso.storage, caso.bucket_name)[0]
    assert fluxo["etapa"] == "falha"
    resposta = client.post("/triagem/reprocessar", json={"documento_id": "001", "origem_oci_path": chave_fluxo("001", fluxo["execucao_id"]), "canal_origem": "Ambulatorio"})
    assert resposta.status_code == 200
    assert all(snapshot(caso)[k] == v for k, v in antes.items())


def test_legados_distintos_sem_migracao_destrutiva(contexto):
    client, caso, _, _ = contexto
    for pasta in ("processados/rotina", "processados/urgentes", "auditoria_humana"):
        caso.storage.salvar_json(caso.bucket_name, pasta + "/001.json", {"documento_id": "001", "status": "processado", "canal_origem": pasta})
    antes = snapshot(caso)
    assert client.post("/triagem", json=payload()).status_code == 409
    historico = client.get("/triagem/historico").json()
    assert len(historico) == 3 and len({d["registro_id"] for d in historico}) == 3
    assert all(d["legado"] for d in historico)
    assert len(consultar_fluxo(caso.storage, caso.bucket_name)) == 3
    assert snapshot(caso) == antes
    assert client.post("/triagem/reprocessar", json={"documento_id": "001", "origem_oci_path": historico[0]["registro_id"], "canal_origem": "Teste"}).status_code == 409


def test_homologacao_preserva_outras_execucoes(contexto):
    client, caso, llm, _ = contexto
    llm.processar_documento.return_value = resultado_exemplo("revisao")
    primeiro = client.post("/triagem", json=payload()).json()
    segundo = client.post("/triagem/reprocessar", json={"documento_id": "001", "origem_oci_path": primeiro["armazenamento_oci"]["caminho_objeto"], "canal_origem": "Ambulatorio"}).json()
    for doc in (primeiro, segundo):
        resposta = client.post("/triagem/homologar", json={"documento_id": "001", "origem_oci_path": doc["armazenamento_oci"]["caminho_objeto"],
            "paciente_nome": "Paciente sintético", "crm_retificado": "123-SP", "diagnostico": "Teste", "cid_homologado": "Z00",
            "destino_aprovado": "Farmacia_Hospitalar", "parecer_auditor": "Conferido", "decisao": "aprovar"})
        assert resposta.status_code == 200
    historico = client.get("/triagem/historico").json()
    assert len(historico) == 2
    assert len({d["registro_id"] for d in historico}) == 2
    assert all(r["etapa"] == "encaminhados" for r in consultar_fluxo(caso.storage, caso.bucket_name))


def test_reprocessar_valida_origem_identidade_e_original(contexto):
    client, caso, llm, _ = contexto
    doc = client.post("/triagem", json=payload()).json()
    antes = snapshot(caso)
    llm.reset_mock()
    for origem, documento_id, status in [("recebidos/a.txt", "001", 422),
        ("processados/../a.json", "001", 422), ("processados/inexistente.json", "001", 404),
        (doc["armazenamento_oci"]["caminho_objeto"], "OUTRO", 422)]:
        resposta = client.post("/triagem/reprocessar", json={"documento_id": documento_id, "origem_oci_path": origem, "canal_origem": "Teste"})
        assert resposta.status_code == status
    assert snapshot(caso) == antes
    llm.processar_documento.assert_not_called()


def test_legados_com_mesma_execucao_continuam_distintos(contexto):
    client, caso, _, _ = contexto
    for pasta in ("processados/rotina", "processados/urgentes"):
        caso.storage.salvar_json(caso.bucket_name, pasta + "/001.json", {"documento_id": "001", "execucao_id": "mesma-execucao"})
    assert len(client.get("/triagem/historico").json()) == 2
    assert len(consultar_fluxo(caso.storage, caso.bucket_name)) == 2


def test_oci_escrita_condicional_sem_fallback():
    from oci.exceptions import ServiceError
    from infrastructure.adapters.oci_storage_adapter import OCIStorageAdapter
    with patch("oci.object_storage.ObjectStorageClient"):
        storage = OCIStorageAdapter({}, "teste")
    assert storage.criar_json_exclusivo("bucket", "cadastros/a.json", {"id": "a"})
    assert storage.client.put_object.call_args.kwargs["if_none_match"] == "*"
    storage.client.put_object.side_effect = ServiceError(412, "PreconditionFailed", {}, "Existe")
    assert storage.criar_json_exclusivo("bucket", "cadastros/a.json", {}) is False
    storage.client.put_object.side_effect = ServiceError(503, "Unavailable", {}, "Falha")
    with pytest.raises(ServiceError):
        storage.criar_json_exclusivo("bucket", "cadastros/a.json", {})


def test_reserva_emulada_unica_entre_processos_e_persistente(tmp_path):
    caminho = tmp_path / "reservas.sqlite3"
    codigo = '''
import sys
from infrastructure.adapters.sqlite_reservas import SqliteReservas
print(int(SqliteReservas(sys.argv[1]).criar("namespace", "bucket", "cadastros/001.json")))
'''
    processos = [subprocess.Popen([sys.executable, "-c", codigo, str(caminho)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(4)]
    resultados = []
    for processo in processos:
        saida, erro = processo.communicate(timeout=30)
        assert processo.returncode == 0, erro
        resultados.append(int(saida.strip()))
    assert sorted(resultados) == [0, 0, 0, 1]
    from infrastructure.adapters.sqlite_reservas import SqliteReservas
    assert SqliteReservas(caminho).criar("namespace", "bucket", "cadastros/001.json") is False


def test_seletores_abrem_cada_legado_individualmente():
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    docs = [{"documento_id": "001", "registro_id": f"auditoria_humana/{i}/001.json", "legado": True,
        "canal_origem": f"Origem {i}", "dados_extraidos": {"paciente": {"nome": f"Paciente {i}"}},
        "armazenamento_oci": {"caminho_objeto": f"auditoria_humana/{i}/001.json"}} for i in range(3)]
    raiz = Path(__file__).resolve().parents[2]
    with patch("presentation.web.api_client.consultar", side_effect=lambda caminho: {} if caminho == "integracoes" else docs):
        painel = AppTest.from_file(raiz / "presentation/web/app.py", default_timeout=30).run()
        painel.switch_page("app_pages/documentos.py").run()
        assert not painel.exception
        for doc in docs:
            seletor = next(s for s in painel.selectbox if s.label == "Abrir detalhes do documento")
            seletor.set_value(doc["registro_id"]).run()
            assert not painel.exception
            assert painel.session_state.consulta_documento_id == doc["registro_id"]
        painel.switch_page("app_pages/auditoria.py").run()
        for i, doc in enumerate(docs):
            seletor = next(s for s in painel.selectbox if s.label == "Documento para revisão")
            seletor.set_value(doc["registro_id"]).run()
            assert not painel.exception
            assert painel.text_input[0].value == f"Paciente {i}"
