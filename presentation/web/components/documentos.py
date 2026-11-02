"""Apresentação dos estados reais dos documentos armazenados."""
from hashlib import sha256
from presentation.web.components.layout import nome_destino


def chave_documento(doc):
    return doc.get("registro_id") or doc.get("armazenamento_oci", {}).get("caminho_objeto") or doc.get("execucao_id") or doc["documento_id"]


def rotulo_documento(doc):
    origem = doc.get("canal_origem") or "Origem não registrada"
    data = doc.get("criado_em") or "Data não registrada"
    execucao = doc.get("execucao_id") or "Legado"
    registro = sha256(chave_documento(doc).encode()).hexdigest()[:8]
    return f"{doc['documento_id']} · {origem} · {data} · {execucao} · registro {registro}"


def estado_documento(doc):
    if doc.get("erro_extracao"):
        return "Falha na extração"
    if doc.get("decisao_roteamento", {}).get("requer_auditoria_humana"):
        return "Aguardando revisão"
    return {"processado": "Processado", "erro": "Erro", "em_analise": "Em análise"}.get(doc.get("status"), "Não informado")


def linhas_documentos(documentos):
    return [{
        "Documento": d.get("documento_id", "Não informado"),
        "Execução": d.get("execucao_id") or "Legado",
        "Origem": d.get("canal_origem") or "Não registrada",
        "Data": d.get("criado_em") or "Não registrada",
        "Paciente": (d.get("dados_extraidos", {}).get("paciente") or {}).get("nome") or "Não identificado",
        "Tipo": d.get("classificacao", {}).get("tipo_documento") or "Não identificado",
        "Prioridade": "Não avaliada" if d.get("erro_extracao") else d.get("classificacao", {}).get("nivel_prioridade", "Não informada"),
        "Estado": estado_documento(d),
        "Destino": nome_destino(d.get("decisao_roteamento", {}).get("destino_principal")),
    } for d in documentos]
