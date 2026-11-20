"""Inspeção somente leitura: versionamento, duplicados e originais legados.

Executar no ambiente OCI configurado. Não altera buckets nem documentos.
Não inclui dados clínicos no relatório. Ausência de versão recuperável é uma
pendência de recuperação, não prova de perda sem consultar backups externos.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.settings import settings
from infrastructure.oci_client.storage_factory import get_storage_adapter


def auditar(storage, bucket):
    metadados = storage.client.get_bucket(storage.namespace, bucket).data
    grupos = defaultdict(list)
    originais = set(storage.listar_objetos_por_prefixo(bucket, "recebidos/"))
    for prefixo in ("processados/", "auditoria_humana/"):
        for chave in storage.listar_objetos_por_prefixo(bucket, prefixo):
            if not chave.endswith(".json"):
                continue
            doc = storage.obter_json(bucket, chave)
            if not isinstance(doc, dict) or not doc.get("documento_id"):
                continue
            bruto = doc.get("armazenamento_oci", {}).get("caminho_documento_bruto")
            grupos[doc["documento_id"]].append({"relatorio": chave, "execucao_id": doc.get("execucao_id"),
                "original": bruto, "original_presente": bruto in originais})
    afetados = []
    for documento_id, registros in grupos.items():
        if len(registros) < 2 and all(r["original_presente"] for r in registros):
            continue
        versoes = {}
        for original in {r["original"] for r in registros} - {None}:
            itens, pagina = [], None
            while True:
                resposta = storage.client.list_object_versions(storage.namespace, bucket, prefix=original, page=pagina)
                itens.extend(v for v in resposta.data.items if v.name == original and not v.is_delete_marker)
                pagina = resposta.headers.get("opc-next-page")
                if not pagina:
                    break
            versoes[original] = len(itens)
        afetados.append({"documento_id": documento_id, "registros": registros, "versoes_disponiveis": versoes,
            "situacao": "Verificar conteúdo das versões e backups; não reconstruir original a partir de relatório."})
    return {"bucket": bucket, "versionamento": metadados.versioning,
        "precondicoes_automaticas_ok": metadados.versioning == "Enabled" and not afetados,
        "limites": "O inventário atual não comprova ausência de sobrescritas anteriores. Confirmar backups e perdas com os responsáveis antes da regressão real.",
        "cadastros_com_relatorios": len(grupos), "casos_para_investigacao": afetados}


if __name__ == "__main__":
    adapter = get_storage_adapter()
    if adapter.modo != "oci":
        raise SystemExit("Use somente no ambiente configurado com STORAGE_MODE=oci.")
    print(json.dumps(auditar(adapter, settings.OCI_BUCKET_NAME), ensure_ascii=False, indent=2))
