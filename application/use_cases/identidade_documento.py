"""Identidades estáveis e reserva persistente do cadastro documental."""
from hashlib import sha256

from domain.exceptions import DocumentoJaExiste


def identidade(documento_id):
    return sha256(documento_id.encode("utf-8")).hexdigest()


def chave_cadastro(documento_id):
    return f"cadastros/{identidade(documento_id)}.json"


def caminho_execucao(documento_id, execucao_id):
    return f"{identidade(documento_id)}/{execucao_id}"


def documento_legado_existe(storage, bucket, documento_id):
    # Compatibilidade sem renomear/excluir dados anteriores. Falhas de leitura
    # propagam: nunca admitir cadastro quando a consulta não pôde ser concluída.
    for prefixo in ("recebidos/", "processados/", "auditoria_humana/", "fluxo/"):
        for chave in storage.listar_objetos_por_prefixo(bucket, prefixo):
            if prefixo == "recebidos/":
                if chave.rsplit(".", 1)[0] == f"recebidos/{documento_id}":
                    return True
            elif chave.endswith(".json"):
                doc = storage.obter_json(bucket, chave)
                if isinstance(doc, dict) and doc.get("documento_id") == documento_id:
                    return True
    return False


def reservar_cadastro(storage, bucket, registro):
    documento_id = registro["documento_id"]
    chave = chave_cadastro(documento_id)
    if storage.obter_json(bucket, chave) or documento_legado_existe(storage, bucket, documento_id):
        raise DocumentoJaExiste("ID já cadastrado. Consulte o documento e solicite o reprocessamento explicitamente.")
    if not storage.criar_json_exclusivo(bucket, chave, {
        "documento_id": documento_id, "primeira_execucao_id": registro["execucao_id"],
        "criado_em": registro["criado_em"],
    }):
        raise DocumentoJaExiste("ID já cadastrado. Consulte o documento e solicite o reprocessamento explicitamente.")


def identificar_relatorio(doc, caminho):
    """Anota a resposta de consulta sem modificar o objeto legado persistido."""
    doc = dict(doc)
    doc["registro_id"] = caminho
    doc["legado"] = not doc.get("criado_em")
    doc["armazenamento_oci"] = {**doc.get("armazenamento_oci", {}), "caminho_objeto": caminho}
    return doc
