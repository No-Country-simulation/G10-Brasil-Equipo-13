"""Extração predefinida apenas para os exemplos reconhecidos pelo conteúdo."""
import base64
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from domain.exceptions import FalhaExtracaoIA
from domain.ports.llm_port import LLMPort

EXEMPLOS = Path(__file__).resolve().parents[2] / "presentation_examples"


def normalizar(conteudo):
    texto = conteudo.decode("utf-8-sig") if isinstance(conteudo, bytes) else conteudo
    return texto.replace("\r\n", "\n").strip()


class PresentationLLMAdapter(LLMPort):
    def processar_documento(self, conteudo, tipo_arquivo):
        try:
            # Uploads TXT chegam em base64; texto colado chega diretamente.
            candidatos = [normalizar(conteudo)]
            if isinstance(conteudo, str):
                try:
                    candidatos.append(normalizar(base64.b64decode(conteudo, validate=True)))
                except (ValueError, UnicodeError):
                    pass
            # urgencia_sem_crm não aparece na interface; existe para os testes do Compose.
            for nome in ("rotina", "urgencia", "revisao", "urgencia_sem_crm"):
                esperado = sha256(normalizar((EXEMPLOS / f"{nome}.txt").read_bytes()).encode()).digest()
                if any(sha256(c.encode()).digest() == esperado for c in candidatos):
                    return deepcopy(resultado_exemplo(nome))
        except (UnicodeError, AttributeError):
            pass
        raise FalhaExtracaoIA("exemplo_nao_reconhecido", "Análise simulada: use um dos três arquivos TXT disponíveis em Nova triagem, sem alterar seu conteúdo. Nenhuma LLM foi chamada.")


def resultado_exemplo(nome):
    if nome == "urgencia_sem_crm":
        resultado = resultado_exemplo("urgencia")
        resultado["paciente"] = {"nome": "Pessoa Ficticia Urgencia Sem CRM", "idade": 71}
        resultado["medico_solicitante"]["crm"] = None
        return resultado
    revisao, urgente = nome == "revisao", nome == "urgencia"
    return {
        "tipo_documento": "Laudo de Exame de Imagem" if urgente else "Receituário Médico",
        "especialidade": "Radiologia" if urgente else "Clínica Geral",
        "nivel_prioridade": "Urgente" if urgente else "Rotina",
        "score_confianca": 0.4 if revisao else 0.96,
        "achado_critico": urgente,
        "paciente": {"nome": None if revisao else "Pessoa Ficticia Urgencia" if urgente else "Pessoa Ficticia Rotina", "idade": None if revisao else 67 if urgente else 54},
        "medico_solicitante": {"nome": None if revisao else "Dr. Exemplo" if urgente else "Dra. Exemplo", "crm": None if revisao else "000002-SP" if urgente else "000001-SP"},
        "exame_realizado": "Tomografia" if urgente else None,
        "diagnostico_principal": "Tromboembolismo pulmonar agudo" if urgente else None if revisao else "Hipertensão em acompanhamento",
        "cid_sugerido": None,
        "medicamentos": ["Losartana 50 mg, 1 comprimido ao dia"] if nome == "rotina" else [],
    }
