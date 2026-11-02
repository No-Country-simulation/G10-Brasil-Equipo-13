"""Acompanhamento persistido, sem dependência de um provedor de armazenamento."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4
from application.use_cases.identidade_documento import identificar_relatorio


def chave_fluxo(documento_id, execucao_id=None):
    identidade = sha256(documento_id.encode('utf-8')).hexdigest()
    return f"fluxo/{identidade}/{execucao_id}.json" if execucao_id else f"fluxo/{identidade}.json"


def novo_registro(documento_id, execucao_id=None):
    return {"versao": 1, "documento_id": documento_id, "execucao_id": execucao_id or uuid4().hex,
            "criado_em": datetime.now(timezone.utc).isoformat(), "eventos": []}


def registrar_etapa(storage, bucket, registro, etapa, documento=None, mensagem=None):
    proximo = deepcopy(registro)
    agora = datetime.now(timezone.utc).isoformat()
    proximo.update(etapa=etapa, atualizado_em=agora)
    proximo["eventos"].append({"etapa": etapa, "em": agora})
    if documento is not None:
        proximo["documento"] = documento
    if mensagem:
        proximo["mensagem"] = mensagem
    chave = registro.get("chave_persistida") or chave_fluxo(registro["documento_id"], registro["execucao_id"])
    if not storage.salvar_json(bucket, chave, proximo):
        raise RuntimeError("Não foi possível registrar a etapa do processamento.")
    registro.clear()
    registro.update(proximo)


def concluir_homologacao(storage, bucket, documento, aprovado):
    chave = chave_fluxo(documento["documento_id"], documento.get("execucao_id"))
    registro = storage.obter_json(bucket, chave)
    if not registro:
        chave_legada = chave_fluxo(documento["documento_id"])
        legado = storage.obter_json(bucket, chave_legada)
        if legado and legado.get("execucao_id") == documento.get("execucao_id"):
            registro = {**legado, "chave_persistida": chave_legada}
    if not isinstance(registro, dict) or registro.get("versao") != 1:
        registro = novo_registro(documento["documento_id"], documento.get("execucao_id"))
    if aprovado:
        registrar_etapa(storage, bucket, registro, "processados", documento)
        registrar_etapa(storage, bucket, registro, "encaminhados", documento)
    else:
        registrar_etapa(storage, bucket, registro, "rejeitados", documento)


def etapa_do_documento(doc, caminho):
    if caminho.startswith("processados/rejeitados/"):
        return "rejeitados"
    if doc.get("armazenamento_oci", {}).get("status_backup") == "falha":
        return "falha"
    if doc.get("decisao_roteamento", {}).get("requer_auditoria_humana"):
        return "revisao_humana"
    if doc.get("status") == "erro":
        return "falha"
    if doc.get("status") == "processado":
        return "encaminhados" if doc.get("decisao_roteamento", {}).get("destino_principal") else "processados"
    return "em_analise"


def consultar_fluxo(storage, bucket):
    registros = {}
    for chave in storage.listar_objetos_por_prefixo(bucket, "fluxo/"):
        if chave.endswith(".json"):
            item = storage.obter_json(bucket, chave)
            if item and item.get("versao") == 1:
                item["registro_id"] = chave
                registros[(item["documento_id"], item.get("execucao_id") or chave)] = item
    # Reconcilia decisões já persistidas, inclusive quando a última gravação do
    # acompanhamento falhou. Um resultado de execução anterior não encerra a atual.
    for prefixo in ("processados/", "auditoria_humana/"):
        for chave in storage.listar_objetos_por_prefixo(bucket, prefixo):
            if not chave.endswith(".json"):
                continue
            doc = storage.obter_json(bucket, chave)
            if not doc or not doc.get("documento_id"):
                continue
            doc = identificar_relatorio(doc, chave)
            identidade = (doc["documento_id"], doc.get("execucao_id") or chave)
            anterior = registros.get(identidade)
            # Duplicados anteriores podem inclusive compartilhar execucao_id.
            # Nunca substituir um relatório já reconciliado por outro caminho.
            if anterior and anterior.get("registro_id", "").startswith(("processados/", "auditoria_humana/")) and anterior["registro_id"] != chave:
                identidade = (doc["documento_id"], chave)
                anterior = None
            item = deepcopy(anterior) if anterior else {
                "documento_id": doc["documento_id"], "execucao_id": doc.get("execucao_id"),
                "eventos": [], "atualizado_em": None, "registro_anterior": True,
            }
            etapa = etapa_do_documento(doc, chave)
            if anterior and etapa != anterior.get("etapa"):
                item.update(atualizado_em=None, registro_reconciliado=True)
            item.update(etapa=etapa, documento=doc)
            item["registro_id"] = chave
            registros[identidade] = item
    return sorted(registros.values(), key=lambda r: (r.get("atualizado_em") or "", r["documento_id"]), reverse=True)
