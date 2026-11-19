"""Regressões das decisões de identidade e classificação da issue #31."""
import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import oci
import pytest
from pydantic import ValidationError

from application.dtos.input_request import TriagemRequestDTO
from application.dtos.output_response import ClassificacaoDTO
from application.use_cases.processar_triagem import ProcessarTriagemUseCase
from domain.exceptions import FalhaExtracaoIA
from infrastructure.adapters.memory_storage_adapter import MemoryStorageAdapter
from infrastructure.adapters.oci_storage_adapter import OCIStorageAdapter
from infrastructure.adapters.openai_llm_adapter import OpenAILLMAdapter
from infrastructure.adapters.presentation_llm_adapter import resultado_exemplo
from infrastructure.adapters.schemas_llm import ExtracaoClinicaLLMSchema
from infrastructure.adapters.sqlite_reservas import SqliteReservas


def test_cancelamento_concorrente_nao_apaga_nova_reserva():
    storage = MemoryStorageAdapter()
    storage.criar_json_exclusivo("b", "cadastro", {"primeira_execucao_id": "antiga"})
    with ThreadPoolExecutor(max_workers=2) as pool:
        resultados = list(pool.map(lambda _: storage.cancelar_cadastro("b", "cadastro", "fluxo", "antiga"), range(2)))
    assert sorted(resultados) == [False, True]
    storage.criar_json_exclusivo("b", "cadastro", {"primeira_execucao_id": "nova"})
    assert not storage.cancelar_cadastro("b", "cadastro", "fluxo", "antiga")
    assert storage.obter_json("b", "cadastro")["primeira_execucao_id"] == "nova"


@pytest.mark.parametrize("dono,etag,status", [("outra", "v1", None), ("minha", None, None), ("minha", "v1", 412), ("minha", "v1", None)])
def test_oci_cancelamento_condicional(dono, etag, status):
    storage = object.__new__(OCIStorageAdapter)
    storage.namespace, storage.reservas, storage.client = "n", None, Mock()
    storage.client.get_object.return_value = Mock(
        data=Mock(content=json.dumps({"primeira_execucao_id": dono}).encode()),
        headers={"etag": etag},
    )
    if status:
        storage.client.delete_object.side_effect = oci.exceptions.ServiceError(status, "conflito", {}, "alterado")
    esperado = dono == "minha" and bool(etag) and not status
    assert storage.cancelar_cadastro("b", "cadastro", "fluxo", "minha") == esperado
    if dono == "minha" and etag:
        assert storage.client.delete_object.call_args_list[0].kwargs == {"if_match": "v1"}
    else:
        storage.client.delete_object.assert_not_called()


def test_sqlite_nao_libera_reserva_se_exclusao_condicional_falhar(tmp_path):
    reservas = SqliteReservas(tmp_path / "r.db")
    assert reservas.criar("n", "b", "c")
    assert not reservas.cancelar_se("n", "b", "c", lambda: False)
    assert not reservas.criar("n", "b", "c")
    assert reservas.cancelar_se("n", "b", "c", lambda: True)
    assert reservas.criar("n", "b", "c")


def test_consulta_inconclusiva_preserva_reserva():
    storage = MemoryStorageAdapter()
    registro = {"documento_id": "doc", "execucao_id": "e", "eventos": [], "caminho_documento_bruto": "recebidos/doc"}
    caso = ProcessarTriagemUseCase(Mock(), storage, Mock(), "b")
    storage.obter_arquivo = Mock(side_effect=TimeoutError())
    storage.cancelar_cadastro = Mock()
    caso._tratar_interrupcao(registro, True)
    storage.cancelar_cadastro.assert_not_called()
    assert registro["etapa"] == "falha"


def test_fallback_openai_vira_falha_explicita_e_revisao_humana():
    adapter = object.__new__(OpenAILLMAdapter)
    adapter.model_name, adapter.client = "teste", Mock()
    adapter.client.beta.chat.completions.parse.side_effect = ValueError("resposta invalida")
    with pytest.raises(FalhaExtracaoIA):
        adapter.processar_documento("sintetico", "TEXTO")
    caso = ProcessarTriagemUseCase(adapter, MemoryStorageAdapter(), Mock(), "b")
    resultado = caso.executar(TriagemRequestDTO(documento_id="doc", tipo_arquivo="TEXTO", documento_texto="sintetico", canal_origem="Recepcao"))
    assert resultado.decisao_roteamento.destino_principal == "Fila_Revisao_Humana"
    assert resultado.classificacao.tipo_documento == "Documento Clínico Não Identificado"
    assert resultado.status.value == "erro"


@pytest.mark.parametrize("tipo", ["Documento Clínico Não Identificado", "Guia TISS"])
def test_schema_ia_rejeita_fallback_mas_dto_legado_permanece_compativel(tipo):
    dados = resultado_exemplo("rotina")
    dados["tipo_documento"] = tipo
    with pytest.raises(ValidationError):
        ExtracaoClinicaLLMSchema.model_validate(dados)
    assert ClassificacaoDTO(tipo_documento=tipo, especialidade="não identificada", nivel_prioridade="Rotina", score_confianca_classificacao=0).tipo_documento == tipo


def test_falha_ao_arquivar_tentativa_nao_libera_reserva():
    storage = MemoryStorageAdapter()
    caso = ProcessarTriagemUseCase(Mock(), storage, Mock(), "b")
    registro = {"documento_id": "doc", "execucao_id": "e", "eventos": []}
    storage.salvar_json = Mock(return_value=False)
    storage.cancelar_cadastro = Mock()
    with pytest.raises(RuntimeError):
        caso._tratar_interrupcao(registro, True)
    storage.cancelar_cadastro.assert_not_called()
