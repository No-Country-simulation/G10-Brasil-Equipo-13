import base64
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
import pytest
from google.genai import errors

from application.dtos.input_request import TriagemRequestDTO
from application.use_cases.processar_triagem import ProcessarTriagemUseCase
from domain.exceptions import FalhaExtracaoIA
from infrastructure.adapters.gemini_llm_adapter import GeminiLLMAdapter
from infrastructure.adapters.memory_storage_adapter import MemoryStorageAdapter


def extracao(**mudancas):
    dados = dict(
        tipo_documento="Receituário Médico", especialidade="Clínica Geral",
        nivel_prioridade="Rotina", score_confianca=.96,
        paciente={"nome": "Paciente Fictício", "idade": 40},
        medico_solicitante={"nome": "Médica Fictícia", "crm": "123456-SP"},
        diagnostico_principal="Exemplo sintético", medicamentos=["Medicamento fictício"],
        achado_critico=False,
    )
    dados.update(mudancas)
    return dados


@pytest.mark.parametrize("status,codigo", [
    (400, "requisicao_invalida"), (401, "acesso_negado"),
    (403, "acesso_negado"), (404, "modelo_indisponivel"),
    (429, "limite_uso"), (503, "servico_indisponivel"),
])
def test_falha_classificada_e_tentativas_limitadas(status, codigo):
    erro = errors.APIError(status, {"error": {"message": "detalhe sensível"}})
    with patch("google.genai.Client") as client, patch("infrastructure.adapters.gemini_llm_adapter.time.sleep") as sleep:
        chamada = client.return_value.models.generate_content
        chamada.side_effect = erro
        adapter = GeminiLLMAdapter("teste")
        with pytest.raises(FalhaExtracaoIA) as falha:
            adapter.processar_documento("texto", "TEXTO")
        assert falha.value.codigo == codigo
        assert "sensível" not in str(falha.value)
        tentativas = 3 if status in (429, 503) else 1
        assert chamada.call_count == tentativas
        assert sleep.call_count == tentativas - 1


def test_sobrecarga_recupera_sem_multiplicar_retries_sdk():
    with patch("google.genai.Client") as client, patch("infrastructure.adapters.gemini_llm_adapter.time.sleep"):
        chamada = client.return_value.models.generate_content
        chamada.side_effect = [errors.APIError(503, {}), SimpleNamespace(parsed=extracao())]
        adapter = GeminiLLMAdapter("teste", model_name="modelo-configurado")
        assert adapter.processar_documento("texto", "TEXTO")["score_confianca"] == .96
        assert chamada.call_count == 2
        assert chamada.call_args.kwargs["model"] == "modelo-configurado"
        assert client.call_args.kwargs["http_options"].retry_options.attempts == 1


@pytest.mark.parametrize("parsed", [None, {}, extracao(score_confianca=1.5), extracao(paciente={"nome": "Teste", "idade": 180}), extracao(nivel_prioridade="qualquer")])
def test_resposta_invalida_nao_vira_extracao(parsed):
    with patch("google.genai.Client") as client:
        client.return_value.models.generate_content.return_value.parsed = parsed
        with pytest.raises(FalhaExtracaoIA) as erro:
            GeminiLLMAdapter("teste").processar_documento("texto", "TEXTO")
        assert erro.value.codigo == "resposta_invalida"
        assert client.return_value.models.generate_content.call_count == 1


def test_erro_rede_tem_tentativas_limitadas():
    with patch("google.genai.Client") as client, patch("infrastructure.adapters.gemini_llm_adapter.time.sleep"):
        client.return_value.models.generate_content.side_effect = httpx.ConnectError("offline")
        with pytest.raises(FalhaExtracaoIA) as erro:
            GeminiLLMAdapter("teste", max_attempts=2).processar_documento("texto", "TEXTO")
        assert erro.value.codigo == "servico_indisponivel"
        assert client.return_value.models.generate_content.call_count == 2


@pytest.mark.parametrize("tipo,conteudo,mime", [
    ("PDF", b"%PDF-1.4 exemplo", "application/pdf"),
    ("IMAGEM", b"\x89PNG\r\n\x1a\nexemplo", "image/png"),
    ("IMAGEM", b"\xff\xd8exemplo", "image/jpeg"),
])
def test_binario_enviado_com_mime_correto(tipo, conteudo, mime):
    with patch("google.genai.Client") as client:
        client.return_value.models.generate_content.return_value.parsed = extracao()
        GeminiLLMAdapter("teste").processar_documento(base64.b64encode(conteudo).decode(), tipo)
        parte = client.return_value.models.generate_content.call_args.kwargs["contents"][0]
        assert parte.inline_data.mime_type == mime
        assert parte.inline_data.data == conteudo


@pytest.mark.parametrize("dados,destino,prefixo", [
    (extracao(), "Farmacia_Hospitalar", "processados/rotina/"),
    (extracao(tipo_documento="Laudo", nivel_prioridade="Urgente", achado_critico=True), "Fila_Emergencia_Medica", "processados/urgentes/"),
    (extracao(score_confianca=.4, paciente={"nome": None, "idade": None}), "Fila_Revisao_Humana", "auditoria_humana/"),
])
def test_cenarios_completos_com_extracao_simulada(dados, destino, prefixo):
    with patch("google.genai.Client") as client:
        client.return_value.models.generate_content.return_value.parsed = dados
        storage = MemoryStorageAdapter()
        notifier = Mock()
        caso = ProcessarTriagemUseCase(GeminiLLMAdapter("teste"), storage, notifier, "teste")
        resposta = caso.executar(TriagemRequestDTO(documento_id="SINTETICO", tipo_arquivo="TEXTO", documento_texto="Exemplo fictício", canal_origem="Teste"))
        assert resposta.status == "processado"
        assert resposta.erro_extracao is None
        assert resposta.decisao_roteamento.destino_principal == destino
        assert resposta.armazenamento_oci.caminho_objeto.startswith(prefixo)
        salvo = storage.obter_json("teste", resposta.armazenamento_oci.caminho_objeto)
        assert salvo["status"] == "processado"
        if destino == "Fila_Emergencia_Medica":
            notifier.enviar_alerta_urgencia.assert_called_once()


def test_falha_ia_persiste_erro_em_auditoria_sem_alerta_clinico():
    llm = Mock()
    llm.processar_documento.side_effect = FalhaExtracaoIA("modelo_indisponivel", "Modelo indisponível.")
    storage = MemoryStorageAdapter()
    notifier = Mock()
    caso = ProcessarTriagemUseCase(llm, storage, notifier, "teste")
    resposta = caso.executar(TriagemRequestDTO(documento_id="FALHA", tipo_arquivo="TEXTO", documento_texto="Documento fictício", canal_origem="Teste"))
    assert resposta.status == "erro"
    assert resposta.erro_extracao.codigo == "modelo_indisponivel"
    assert resposta.decisao_roteamento.requer_auditoria_humana
    assert "Extração não realizada" in resposta.decisao_roteamento.justificativa_roteamento
    assert storage.obter_json("teste", resposta.armazenamento_oci.caminho_objeto)["status"] == "erro"
    notifier.enviar_alerta_urgencia.assert_not_called()
