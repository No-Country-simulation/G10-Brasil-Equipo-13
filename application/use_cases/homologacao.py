"""Identidade e estado da decisão de uma pendência de auditoria."""
from application.use_cases.identidade_documento import identidade


PREFIXO_DECISOES = "homologacoes/decisoes/"
PREFIXO_CONCLUIDAS = "homologacoes/concluidas/"


def chave_decisao(origem):
    return f"{PREFIXO_DECISOES}{identidade(origem)}.json"


def chave_conclusao(origem):
    return f"{PREFIXO_CONCLUIDAS}{identidade(origem)}.json"
