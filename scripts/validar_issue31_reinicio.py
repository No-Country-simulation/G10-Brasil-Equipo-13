"""Teste HTTP sintético em duas fases, exclusivamente contra o emulador.

gravar -> reiniciar a API de testes -> conferir. Estado fica em /tmp.
"""
import argparse
import json
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests

from application.use_cases.identidade_documento import identidade, chave_cadastro
from config.settings import settings
from infrastructure.oci_client.storage_factory import get_storage_adapter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("acao", choices=["gravar", "conferir"])
    args = parser.parse_args()
    if settings.STORAGE_MODE != "emulator":
        raise SystemExit("Este teste permite somente STORAGE_MODE=emulator.")
    estado = Path("/tmp/issue31-reinicio.json")
    api = "http://127.0.0.1:8000/triagem"
    storage, bucket = get_storage_adapter(), settings.OCI_BUCKET_NAME
    if args.acao == "gravar":
        payload = {"documento_id": "ISSUE31-REINICIO-" + uuid4().hex,
            "tipo_arquivo": "TEXTO", "documento_texto": Path("presentation_examples/rotina.txt").read_text(),
            "canal_origem": "Teste de reinício"}
        resposta = requests.post(api, json=payload, timeout=30)
        resposta.raise_for_status()
        doc = resposta.json()
        caminhos = [doc["armazenamento_oci"]["caminho_objeto"], doc["armazenamento_oci"]["caminho_documento_bruto"]]
        estado.write_text(json.dumps({"payload": payload, "doc": doc,
            "objetos": {k: storage.obter_arquivo(bucket, k).hex() for k in caminhos}}))
        print("OK: documento sintético e cópias de conferência registrados; reinicie a API de testes.")
        return
    anterior = json.loads(estado.read_text())
    payload, doc = anterior["payload"], anterior["doc"]
    resposta = requests.post(api, json=payload, timeout=30)
    assert resposta.status_code == 409, resposta.text
    for chave, conteudo in anterior["objetos"].items():
        assert storage.obter_arquivo(bucket, chave).hex() == conteudo
    resposta = requests.post(api + "/reprocessar", json={"documento_id": payload["documento_id"],
        "origem_oci_path": doc["armazenamento_oci"]["caminho_objeto"], "canal_origem": "Após reinício"}, timeout=30)
    resposta.raise_for_status()
    assert resposta.json()["execucao_id"] != doc["execucao_id"]
    for chave, conteudo in anterior["objetos"].items():
        assert storage.obter_arquivo(bucket, chave).hex() == conteudo
    historico = requests.get(api + "/historico", timeout=30)
    historico.raise_for_status()
    assert len([d for d in historico.json() if d["documento_id"] == payload["documento_id"]]) == 2
    # Remove exclusivamente os dados sintéticos criados por este teste.
    identificador = identidade(payload["documento_id"])
    for prefixo in ("recebidos/", "processados/rotina/", "fluxo/"):
        for chave in storage.listar_objetos_por_prefixo(bucket, prefixo + identificador + "/"):
            storage.client.delete_object(storage.namespace, bucket, chave)
    storage.client.delete_object(storage.namespace, bucket, chave_cadastro(payload["documento_id"]))
    estado.unlink()
    print("OK: HTTP 409 após reinício, original e relatório preservados, reprocessamento em nova execução; dados de teste removidos.")


if __name__ == "__main__":
    main()
