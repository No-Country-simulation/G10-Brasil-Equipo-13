import pytest
from pydantic import ValidationError

from unittest.mock import MagicMock, patch
from infrastructure.adapters.gemini_llm_adapter import GeminiLLMAdapter
from infrastructure.adapters.schemas_llm import ExtracaoClinicaLLMSchema, PacienteLLMSchema, MedicoSolicitanteLLMSchema


def test_extracao_gemini_sucesso():
    # Mock do retorno da API
    mock_dados = ExtracaoClinicaLLMSchema(
        tipo_documento="Laudo de Exame de Imagem",
        especialidade="Radiologia / Pneumologia",
        nivel_prioridade="Urgente",
        score_confianca=0.99,
        paciente=PacienteLLMSchema(nome="Carlos Eduardo Mendes", idade=52),
        medico_solicitante=MedicoSolicitanteLLMSchema(nome="Dra. Renata Silveira", crm="145892-SP"),
        exame_realizado="Tomografia de Torax com contraste",
        diagnostico_principal="Tromboembolismo Pulmonar Agudo (TEP)",
        cid_sugerido="I26.9",
        medicamentos=[],
        achado_critico=True,
    )

    with patch("google.genai.Client") as mock_client_cls:
        mock_instance = MagicMock()
        mock_client_cls.return_value = mock_instance
        mock_instance.models.generate_content.return_value.parsed = mock_dados

        adapter = GeminiLLMAdapter(api_key="mock_key")
        resultado = adapter.processar_documento("Laudo de TEP agudo", "TEXTO")

        assert resultado["score_confianca"] == 0.99
        assert resultado["achado_critico"] is True
        assert resultado["diagnostico_principal"] == "Tromboembolismo Pulmonar Agudo (TEP)"
        assert resultado["paciente"]["nome"] == "Carlos Eduardo Mendes"

@pytest.mark.parametrize("categoria", [
    "Receituário Médico",
    "Laudo de Exame Laboratorial",
    "Laudo de Exame de Imagem",
    "Guia de Solicitação de Procedimento",
    "Relatório de Alta/Internação",
    "Autorização Administrativa",
    "Atestado Médico",
])
def test_categorias_documentais_validas(categoria):
    dados = {
        "tipo_documento": categoria,
        "especialidade": "Clínica Geral",
        "nivel_prioridade": "Rotina",
        "score_confianca": 0.99,
        "paciente": {"nome": "Paciente sintético", "idade": 34},
        "medico_solicitante": {"nome": "Médico fictício", "crm": "123456-SP"},
        "achado_critico": False,
    }

    resultado = ExtracaoClinicaLLMSchema.model_validate(dados)
    assert resultado.tipo_documento == categoria


def test_categoria_documental_nao_permitida():
    dados = {
        "tipo_documento": "Guia TISS",
        "especialidade": "Clínica Geral",
        "nivel_prioridade": "Rotina",
        "score_confianca": 0.99,
        "paciente": {"nome": "Paciente sintético", "idade": 34},
        "medico_solicitante": {"nome": "Médico fictício", "crm": "123456-SP"},
        "achado_critico": False,
    }

    with pytest.raises(ValidationError):
        ExtracaoClinicaLLMSchema.model_validate(dados)

def test_normalizacao_entidades_html():
    mock_dados = ExtracaoClinicaLLMSchema(
        tipo_documento="Receituário Médico",
        especialidade="Clínica Geral",
        nivel_prioridade="Rotina",
        score_confianca=0.99,
        paciente=PacienteLLMSchema(
            nome="Luana Gon&ccedil;alves Alves",
            idade=34,
        ),
        medico_solicitante=MedicoSolicitanteLLMSchema(
            nome="Médico fictício",
            crm="123456-SP",
        ),
        diagnostico_principal="Sepse n&atilde;o especificada",
        medicamentos=["&Aacute;cido acetilsalic&iacute;lico"],
        achado_critico=False,
    )

    with patch("google.genai.Client") as mock_client_cls:
        mock_client_cls.return_value.models.generate_content.return_value.parsed = mock_dados

        adapter = GeminiLLMAdapter(api_key="mock_key")
        resultado = adapter.processar_documento("Documento sintético", "TEXTO")

    assert resultado["paciente"]["nome"] == "Luana Gonçalves Alves"
    assert resultado["diagnostico_principal"] == "Sepse não especificada"
    assert resultado["medicamentos"] == ["Ácido acetilsalicílico"]