import base64
import warnings
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from application.use_cases.processar_triagem import ProcessarTriagemUseCase
from infrastructure.adapters.memory_storage_adapter import MemoryStorageAdapter
from infrastructure.adapters.presentation_llm_adapter import resultado_exemplo
from infrastructure.oci_client.client_factory import get_triagem_use_case
from presentation.api.main import app


@pytest.fixture
def contexto():
    llm, notifier = Mock(), Mock()
    llm.processar_documento.return_value = resultado_exemplo("urgencia")
    caso = ProcessarTriagemUseCase(llm, MemoryStorageAdapter(), notifier, "teste")
    app.dependency_overrides[get_triagem_use_case] = lambda: caso
    try:
        with TestClient(app) as client:
            yield client, caso, llm, notifier
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("pendencia", ["crm", "paciente", "score", "conflito", None])
def test_urgencia_preserva_alerta_e_pendencias(contexto, pendencia):
    client, caso, llm, notifier = contexto
    dados = llm.processar_documento.return_value
    if pendencia == "crm":
        dados["medico_solicitante"]["crm"] = None
    elif pendencia == "paciente":
        dados["paciente"]["nome"] = None
    elif pendencia == "score":
        dados["score_confianca"] = .4
    elif pendencia == "conflito":
        dados["exame_realizado"] = dados["diagnostico_principal"] = None
    resp = client.post("/triagem", json=dict(documento_id="CRITICO", tipo_arquivo="TEXTO", documento_texto="Sintético", canal_origem="Teste"))
    assert resp.status_code == 200
    doc = resp.json()
    decisao = doc["decisao_roteamento"]
    assert decisao["destino_principal"] == "Fila_Emergencia_Medica"
    assert decisao["requer_auditoria_humana"] is (pendencia is not None)
    assert decisao["notificacao_gerada"]["canal"] == "Alerta_Plantao_Medico"
    adicionais = decisao["notificacoes_adicionais"]
    assert [n["canal"] for n in adicionais] == (["Email_Auditoria"] if pendencia else [])
    # O alerta ao plantão sai primeiro; o e-mail de auditoria não o substitui.
    chamadas = [c.kwargs for c in notifier.enviar_alerta_urgencia.call_args_list]
    assert chamadas == [decisao["notificacao_gerada"], *adicionais]
    path = doc["armazenamento_oci"]["caminho_objeto"]
    assert path.startswith("auditoria_humana/" if pendencia else "processados/urgentes/")
    assert caso.storage.obter_json("teste", path)["decisao_roteamento"] == decisao
    assert len(client.get("/triagem/filas/urgencias").json()) == 1
    assert len(client.get("/triagem/filas/auditoria").json()) == (1 if pendencia else 0)
    fluxo = client.get("/triagem/filas/processamento").json()[0]
    assert fluxo["etapa"] == ("revisao_humana" if pendencia else "encaminhados")


@pytest.mark.parametrize("bom", [b"", b"\xef\xbb\xbf"])
def test_upload_txt_entrega_texto_legivel_e_preserva_original(contexto, bom):
    client, caso, llm, _ = contexto
    texto = "Paciente: João\r\nConclusão: avaliação clínica.\n"
    bruto = bom + texto.encode("utf-8")
    resp = client.post("/triagem/upload", data={"documento_id": "TXT", "canal_origem": "Teste"}, files={"arquivo": ("caso.txt", bruto, "text/plain")})
    assert resp.status_code == 200
    llm.processar_documento.assert_called_once_with(conteudo=texto, tipo_arquivo="TEXTO")
    assert caso.storage.obter_arquivo("teste", resp.json()["armazenamento_oci"]["caminho_documento_bruto"]) == bruto


@pytest.mark.parametrize("nome,mime,bruto,status", [
    ("caso.zip", "application/zip", b"PK123", 415),
    ("caso.txt", "text/plain", b"\xff", 422),
    ("caso.txt", "text/plain", b"abc\x00def", 422),
    ("caso.txt", "text/plain", b"   ", 422),
    ("caso.txt", "text/plain", b"", 400),
])
def test_upload_invalido_nao_inicia_llm(contexto, nome, mime, bruto, status):
    client, _, llm, _ = contexto
    resp = client.post("/triagem/upload", data={"documento_id": "INVALIDO", "canal_origem": "Teste"}, files={"arquivo": (nome, bruto, mime)})
    assert resp.status_code == status
    llm.processar_documento.assert_not_called()


def test_falha_no_alerta_urgente_nao_impede_email_de_auditoria(contexto):
    client, _, llm, notifier = contexto
    llm.processar_documento.return_value["medico_solicitante"]["crm"] = None
    notifier.enviar_alerta_urgencia.side_effect = [RuntimeError("falha simulada"), True]
    resp = client.post("/triagem", json=dict(documento_id="CRITICO", tipo_arquivo="TEXTO", documento_texto="Sintético", canal_origem="Teste"))
    assert resp.status_code == 200
    canais = [c.kwargs["canal"] for c in notifier.enviar_alerta_urgencia.call_args_list]
    assert canais == ["Alerta_Plantao_Medico", "Email_Auditoria"]


def test_rotas_sem_pendencia_nao_geram_notificacoes_adicionais(contexto):
    client, _, llm, _ = contexto
    llm.processar_documento.return_value = resultado_exemplo("rotina")
    resp = client.post("/triagem", json=dict(documento_id="ROTINA", tipo_arquivo="TEXTO", documento_texto="Sintético", canal_origem="Teste"))
    assert resp.status_code == 200
    assert resp.json()["decisao_roteamento"]["notificacoes_adicionais"] == []


def test_erro_422_sem_aviso_de_deprecacao(contexto):
    client, _, _, _ = contexto
    payload = dict(documento_id="JSON", tipo_arquivo="TEXTO", canal_origem="Teste", arquivo_base64="%%%")
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        resp = client.post("/triagem", json=payload)
    assert resp.status_code == 422


def test_base64_invalido_e_texto_direto_literal(contexto):
    client, _, llm, _ = contexto
    payload = dict(documento_id="JSON", tipo_arquivo="TEXTO", canal_origem="Teste")
    resp = client.post("/triagem", json={**payload, "arquivo_base64": "%%%"})
    assert resp.status_code == 422
    llm.processar_documento.assert_not_called()
    texto = base64.b64encode(b"nao decodificar texto direto").decode()
    resp = client.post("/triagem", json={**payload, "documento_texto": texto})
    assert resp.status_code == 200
    llm.processar_documento.assert_called_once_with(conteudo=texto, tipo_arquivo="TEXTO")
