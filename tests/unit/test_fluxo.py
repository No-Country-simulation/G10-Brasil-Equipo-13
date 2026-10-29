from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from application.use_cases.acompanhar_fluxo import chave_fluxo, consultar_fluxo
from application.use_cases.processar_triagem import ProcessarTriagemUseCase
from application.dtos.input_request import TriagemRequestDTO
from domain.exceptions import FalhaExtracaoIA
from infrastructure.adapters.memory_storage_adapter import MemoryStorageAdapter
from infrastructure.oci_client.client_factory import get_triagem_use_case
from presentation.api.main import app


def dados(score=.96):
    return {"tipo_documento": "Receituário", "especialidade": "Clínica Geral", "nivel_prioridade": "Rotina", "score_confianca": score, "paciente": {"nome": "Paciente sintético", "idade": 34}, "medico_solicitante": {"nome": "Profissional fictício", "crm": "123456-SP"}, "medicamentos": ["Medicação fictícia"], "achado_critico": False}


def caso(llm=None, storage=None):
    adapter = llm or Mock()
    if llm is None:
        adapter.processar_documento.return_value = dados()
    return ProcessarTriagemUseCase(adapter, storage or MemoryStorageAdapter(), Mock(), "teste")


def request(doc_id="FLUXO"):
    return TriagemRequestDTO(documento_id=doc_id, tipo_arquivo="TEXTO", documento_texto="Documento sintético", canal_origem="Teste")


def test_api_consultavel_enquanto_llm_esta_processando():
    entrou, liberar = Event(), Event()
    llm = Mock()

    def extrair(**kwargs):
        entrou.set()
        assert liberar.wait(10)
        return dados()

    llm.processar_documento.side_effect = extrair
    use_case = caso(llm)
    app.dependency_overrides[get_triagem_use_case] = lambda: use_case
    try:
        with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as pool:
            post = pool.submit(client.post, "/triagem", json=request().model_dump(mode="json"))
            try:
                assert entrou.wait(5)
                consulta = pool.submit(client.get, "/triagem/filas/processamento")
                resposta = consulta.result(timeout=3)
                assert resposta.status_code == 200
                assert resposta.json()[0]["etapa"] == "em_analise"
            finally:
                liberar.set()
            assert post.result(timeout=5).status_code == 200
            registro = client.get("/triagem/filas/processamento").json()[0]
            assert registro["etapa"] == "encaminhados"
            assert [e["etapa"] for e in registro["eventos"]] == ["recebidos", "em_analise", "processados", "encaminhados"]
            # Um novo caso de uso sobre o mesmo armazenamento recupera o quadro.
            assert consultar_fluxo(caso(storage=use_case.storage).storage, "teste")[0] == registro
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("decisao,etapa", [("aprovar", "encaminhados"), ("rejeitar", "rejeitados")])
def test_revisao_atualiza_fluxo_sem_duplicar_cartao(decisao, etapa):
    llm = Mock()
    llm.processar_documento.return_value = dados(.4)
    use_case = caso(llm)
    doc = use_case.executar(request())
    assert consultar_fluxo(use_case.storage, "teste")[0]["etapa"] == "revisao_humana"
    app.dependency_overrides[get_triagem_use_case] = lambda: use_case
    try:
        resposta = TestClient(app).post("/triagem/homologar", json={"documento_id": "FLUXO", "origem_oci_path": doc.armazenamento_oci.caminho_objeto, "paciente_nome": "Paciente sintético", "crm_retificado": "123456-SP", "diagnostico": "Teste", "cid_homologado": "Z00", "destino_aprovado": "Farmacia_Hospitalar", "parecer_auditor": "Conferência sintética", "decisao": decisao})
        assert resposta.status_code == 200
        itens = consultar_fluxo(use_case.storage, "teste")
        assert len(itens) == 1
        assert itens[0]["etapa"] == etapa
        assert itens[0]["eventos"][-1]["etapa"] == etapa
    finally:
        app.dependency_overrides.clear()


def test_falha_ia_retida_e_interrupcao_inesperada_visivel():
    llm = Mock()
    llm.processar_documento.side_effect = FalhaExtracaoIA("teste", "Indisponibilidade sintética")
    use_case = caso(llm)
    use_case.executar(request("RETIDO"))
    item = consultar_fluxo(use_case.storage, "teste")[0]
    assert item["etapa"] == "revisao_humana"
    assert item["documento"]["erro_extracao"]
    llm.processar_documento.side_effect = RuntimeError("Interrupção sintética")
    with pytest.raises(RuntimeError):
        use_case.executar(request("INTERROMPIDO"))
    assert next(i for i in consultar_fluxo(use_case.storage, "teste") if i["documento_id"] == "INTERROMPIDO")["etapa"] == "falha"


def test_legacy_sem_timestamp_inventado_e_reexecucao_sem_resultado_antigo():
    use_case = caso()
    storage = use_case.storage
    storage.salvar_json("teste", "processados/rotina/LEGADO.json", {"documento_id": "LEGADO", "status": "processado", "decisao_roteamento": {"destino_principal": "Farmacia_Hospitalar"}})
    registro = consultar_fluxo(storage, "teste")[0]
    assert registro["registro_anterior"]
    assert registro["eventos"] == [] and registro["atualizado_em"] is None
    use_case.executar(request("REPETIDO"))
    from application.use_cases.acompanhar_fluxo import novo_registro, registrar_etapa
    novo = novo_registro("REPETIDO")
    registrar_etapa(storage, "teste", novo, "em_analise")
    atual = next(r for r in consultar_fluxo(storage, "teste") if r["documento_id"] == "REPETIDO")
    assert atual["etapa"] == "em_analise" and "documento" not in atual


def test_falha_de_gravacao_nao_inicia_ia_nem_afirma_encaminhamento():
    storage = MemoryStorageAdapter()
    llm = Mock()
    use_case = caso(llm, storage)
    storage.salvar_json = Mock(return_value=False)
    with pytest.raises(RuntimeError):
        use_case.executar(request())
    llm.processar_documento.assert_not_called()


def test_reconcilia_resultado_quando_ultima_etapa_nao_foi_gravada():
    storage = MemoryStorageAdapter()
    original = storage.salvar_json

    def salvar(bucket_name, object_name, json_data):
        if object_name.startswith("fluxo/") and json_data["etapa"] == "encaminhados":
            return False
        return original(bucket_name, object_name, json_data)

    storage.salvar_json = salvar
    resposta = caso(storage=storage).executar(request())
    assert resposta.acompanhamento_fluxo_confirmado is False
    assert storage.obter_json("teste", chave_fluxo("FLUXO", resposta.execucao_id))["etapa"] == "processados"
    reconciliado = consultar_fluxo(storage, "teste")[0]
    assert reconciliado["etapa"] == "encaminhados"
    assert reconciliado["registro_reconciliado"] and reconciliado["atualizado_em"] is None
