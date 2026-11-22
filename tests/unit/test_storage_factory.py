from unittest.mock import Mock, patch

import pytest

from config.settings import Settings
from infrastructure.adapters.memory_storage_adapter import MemoryStorageAdapter
from infrastructure.adapters.oci_storage_adapter import OCIStorageAdapter
from infrastructure.oci_client import storage_factory
from application.dtos.input_request import TriagemRequestDTO
from application.use_cases.processar_triagem import ProcessarTriagemUseCase


@pytest.fixture(autouse=True)
def limpar_cache():
    storage_factory.get_storage_adapter.cache_clear()
    yield
    storage_factory.get_storage_adapter.cache_clear()


def test_env_aceita_caminhos_host_do_compose(tmp_path, monkeypatch):
    monkeypatch.delenv("OCI_CONFIG_HOST_FILE", raising=False)
    monkeypatch.delenv("OCI_KEY_HOST_FILE", raising=False)
    arquivo = tmp_path / ".env"
    arquivo.write_text(
        'OCI_CONFIG_HOST_FILE="C:/privado/config.docker"\n'
        'OCI_KEY_HOST_FILE="C:/privado/chave.pem"\n',
        encoding="utf-8",
    )
    cfg = Settings(_env_file=arquivo)
    assert cfg.OCI_CONFIG_HOST_FILE == "C:/privado/config.docker"
    assert cfg.OCI_KEY_HOST_FILE == "C:/privado/chave.pem"


def test_memoria_isola_buckets():
    storage = MemoryStorageAdapter()
    storage.salvar_json("a", "doc.json", {"id": "a"})
    assert storage.obter_json("b", "doc.json") is None
    assert storage.listar_objetos_por_prefixo("b", "") == []


def test_memoria_explicita_nao_inicializa_sdk():
    config = Settings(APP_MODE="operational", STORAGE_MODE="memory", _env_file=None)
    with patch.object(storage_factory, "settings", config), patch("oci.object_storage.ObjectStorageClient") as client:
        assert storage_factory.get_storage_adapter().modo == "simulado"
        client.assert_not_called()


def test_nuvem_com_credenciais_invalidas_nao_cai_em_memoria():
    config = Settings(APP_MODE="operational", STORAGE_MODE="oci", _env_file=None)
    with patch.object(storage_factory, "settings", config), patch("oci.config.from_file", side_effect=RuntimeError("credenciais inválidas")):
        with pytest.raises(RuntimeError):
            storage_factory.get_storage_adapter()


def test_emulador_usa_sdk_nativo_e_namespace_descoberto():
    config = Settings(APP_MODE="operational", STORAGE_MODE="emulator", _env_file=None)
    with patch.object(storage_factory, "settings", config), patch("oci.object_storage.ObjectStorageClient") as cls:
        client = cls.return_value
        client.get_namespace.return_value.data = "namespace-local"
        adapter = storage_factory.get_storage_adapter()
        assert isinstance(adapter, OCIStorageAdapter)
        assert adapter.modo == "emulador_oci"
        assert adapter.namespace == "namespace-local"
        assert cls.call_args.kwargs["service_endpoint"] == "http://localhost:4599"
        assert "key_content" in cls.call_args.args[0]
        client.get_bucket.assert_called_once()


@pytest.mark.parametrize("endpoint", ["https://objectstorage.oraclecloud.com", "http://example.com", "http://usuario:senha@localhost:4599"])
def test_credenciais_ficticias_somente_para_endpoint_local(endpoint):
    with pytest.raises(ValueError):
        storage_factory.criar_config_emulador(endpoint)


def test_falha_ao_gravar_destino_nao_remove_origem():
    with patch("oci.object_storage.ObjectStorageClient") as cls:
        adapter = OCIStorageAdapter({}, "teste")
        cls.return_value.put_object.side_effect = RuntimeError("armazenamento indisponível")
        with pytest.raises(RuntimeError):
            adapter.mover_objeto("bucket", "auditoria/a.json", "processados/a.json", {"id": "a"})
        cls.return_value.delete_object.assert_not_called()


@pytest.mark.parametrize("excecao", [False, True])
def test_falha_no_original_nao_reporta_backup_completo(excecao):
    storage = MemoryStorageAdapter()
    storage.salvar_arquivo = Mock(return_value="")
    if excecao:
        storage.salvar_arquivo.side_effect = RuntimeError("falha de gravação")
    storage.salvar_json = Mock(return_value=True)
    llm = Mock()
    llm.processar_documento.return_value = {"score_confianca": .3}
    caso = ProcessarTriagemUseCase(llm, storage, Mock(), "teste")
    with pytest.raises(RuntimeError, match="preservar o documento original"):
        caso.executar(TriagemRequestDTO(documento_id="TESTE", tipo_arquivo="TEXTO", documento_texto="Dados fictícios", canal_origem="Teste"))
    llm.processar_documento.assert_not_called()
    assert not any(c.kwargs.get("object_name", "").startswith(("processados/", "auditoria_humana/")) for c in storage.salvar_json.call_args_list)
