"""Homologação real isolada: preflight, executar e conferir após reiniciar a API.

Executar dentro do container de homologação. Usa somente mediflow-testes,
IDs E2E exclusivos e exemplos sintéticos versionados, sem dataset/v2.
Preserva os artefatos de teste para inspeção; nunca limpa o bucket.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from threading import Barrier
import time
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests

from application.use_cases.acompanhar_fluxo import chave_fluxo
from config.settings import settings
from infrastructure.oci_client.storage_factory import get_storage_adapter


API = "http://127.0.0.1:8000/triagem"
EVIDENCIAS = Path("/evidencias")


def salvar(nome, valor):
    EVIDENCIAS.mkdir(parents=True, exist_ok=True)
    (EVIDENCIAS / nome).write_text(json.dumps(valor, ensure_ascii=False, indent=2), encoding="utf-8")


def snapshot(storage):
    objetos, inicio = {}, None
    while True:
        resposta = storage.client.list_objects(
            storage.namespace, settings.OCI_BUCKET_NAME, start=inicio, fields="name,etag"
        )
        for obj in resposta.data.objects:
            objetos[hashlib.sha256(obj.name.encode()).hexdigest()] = obj.etag
        inicio = resposta.data.next_start_with
        if not inicio:
            return objetos


def preflight():
    assert settings.STORAGE_MODE == "oci", "Exige OCI real"
    assert settings.OCI_BUCKET_NAME == "mediflow-testes", "Bucket de testes obrigatório"
    assert settings.APP_MODE == "operational", "Exige modo operacional"
    storage = get_storage_adapter()
    bucket = storage.client.get_bucket(storage.namespace, settings.OCI_BUCKET_NAME).data
    resultado = {"em": datetime.now(timezone.utc).isoformat(), "bucket": bucket.name,
                 "versionamento": bucket.versioning, "modelo": settings.GEMINI_MODEL_NAME,
                 "webhook_configurado": bool(settings.WEBHOOK_URL)}
    salvar("preflight.json", resultado)
    assert bucket.versioning == "Enabled", "Habilite Object Versioning antes de gravar"
    limite = time.monotonic() + 40
    while True:
        try:
            resposta = requests.get(API.removesuffix("/triagem") + "/health", timeout=2)
            if resposta.status_code == 200:
                break
        except requests.RequestException:
            pass
        if time.monotonic() >= limite:
            raise RuntimeError("API isolada não ficou pronta em 40 segundos")
        time.sleep(1)
    return storage


def pedir(caminho="", **kwargs):
    resposta = requests.post(API + caminho, timeout=180, **kwargs)
    return resposta


def conferir_documento(storage, doc, original=None):
    assert not doc.get("erro_extracao"), "Falha de extração real"
    assert doc["armazenamento_oci"]["status_backup"] == "sucesso"
    assert doc["acompanhamento_fluxo_confirmado"] is True
    paths = doc["armazenamento_oci"]
    bruto = storage.obter_arquivo(settings.OCI_BUCKET_NAME, paths["caminho_documento_bruto"])
    if original is not None:
        assert bruto == original, "Original divergiu"
    relatorio = storage.obter_json(settings.OCI_BUCKET_NAME, paths["caminho_objeto"])
    fluxo = storage.obter_json(settings.OCI_BUCKET_NAME, chave_fluxo(doc["documento_id"], doc["execucao_id"]))
    assert relatorio["execucao_id"] == fluxo["execucao_id"] == doc["execucao_id"]
    assert relatorio["canal_origem"] == doc["canal_origem"]
    return {"original": hashlib.sha256(bruto).hexdigest(),
            "relatorio": hashlib.sha256(storage.obter_arquivo(settings.OCI_BUCKET_NAME, paths["caminho_objeto"])).hexdigest()}


def executar():
    storage = preflight()
    baseline = snapshot(storage)
    run = "E2E-OCI-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    estado = {"run": run, "baseline": baseline, "documentos": [], "checks": []}
    salvar("estado.json", estado)

    def registrar(nome, doc, original=None):
        hashes = conferir_documento(storage, doc, original)
        estado["documentos"].append({"cenario": nome, "doc": doc, "hashes": hashes})
        salvar("estado.json", estado)
        print(nome, "OK", doc["documento_id"], flush=True)

    def payload(sufixo, texto):
        return {"documento_id": run + "-" + sufixo, "tipo_arquivo": "TEXTO",
                "documento_texto": texto, "canal_origem": "Ambulatorio"}

    rotina = Path("presentation_examples/rotina.txt").read_text(encoding="utf-8")
    dados = payload("TXT", rotina)
    r = pedir(json=dados)
    r.raise_for_status()
    doc = r.json()
    registrar("cadastro_txt", doc, rotina.encode())
    assert doc["decisao_roteamento"]["destino_principal"] == "Farmacia_Hospitalar"
    for alteracao in ({}, {"documento_texto": "Outro documento sintético"}):
        assert pedir(json={**dados, **alteracao}).status_code == 409
    assert conferir_documento(storage, doc) == estado["documentos"][0]["hashes"]
    estado["checks"].append("duplicado_409_original_preservado")

    bruto = json.dumps({"documento_texto": rotina}, ensure_ascii=False).encode("utf-8-sig")
    r = pedir("/upload", data={"documento_id": run + "-JSON", "canal_origem": "Recepcao"},
              files={"arquivo": ("sintetico.json", bruto, "application/json")})
    r.raise_for_status()
    registrar("upload_json_bom", r.json(), bruto)
    r = pedir("/upload", data={"documento_id": run + "-INVALIDO", "canal_origem": "Recepcao"},
              files={"arquivo": ("invalido.json", b"{invalido", "application/json")})
    assert r.status_code == 422
    estado["checks"].append("json_invalido_422")

    for nome, destino in [("urgencia", "Fila_Emergencia_Medica"), ("revisao", "Fila_Revisao_Humana")]:
        texto = Path(f"presentation_examples/{nome}.txt").read_text(encoding="utf-8")
        r = pedir("/upload", data={"documento_id": run + "-" + nome.upper(), "canal_origem": "Pronto_Socorro"},
                  files={"arquivo": (nome + ".txt", texto.encode(), "text/plain")})
        r.raise_for_status()
        doc_cenario = r.json()
        registrar(nome, doc_cenario, texto.encode())
        assert doc_cenario["decisao_roteamento"]["destino_principal"] == destino

    barreira = Barrier(2)
    concorrente = payload("CORRIDA", rotina)
    def enviar(_):
        barreira.wait(timeout=15)
        return pedir(json=concorrente)
    with ThreadPoolExecutor(max_workers=2) as pool:
        respostas = list(pool.map(enviar, range(2)))
    assert sorted(r.status_code for r in respostas) == [200, 409]
    registrar("concorrencia_http", next(r.json() for r in respostas if r.status_code == 200), rotina.encode())
    estado["checks"].append("concorrencia_uma_criacao_um_409")

    r = pedir("/reprocessar", json={"documento_id": doc["documento_id"],
              "origem_oci_path": doc["armazenamento_oci"]["caminho_objeto"], "canal_origem": "Recepcao"})
    r.raise_for_status()
    novo = r.json()
    assert novo["execucao_id"] != doc["execucao_id"]
    registrar("reprocessamento", novo, rotina.encode())
    assert conferir_documento(storage, doc) == estado["documentos"][0]["hashes"]
    estado["checks"].append("reprocessamento_nova_execucao_original_preservado")
    atual = snapshot(storage)
    assert all(atual.get(chave) == etag for chave, etag in baseline.items()), "Objetos anteriores alterados"
    estado["checks"].append("objetos_anteriores_preservados")
    estado["aguardando_reinicio"] = True
    salvar("estado.json", estado)
    print("FASE 1 OK. Reinicie somente a API isolada e execute conferir.", flush=True)


def conferir():
    storage = preflight()
    estado = json.loads((EVIDENCIAS / "estado.json").read_text(encoding="utf-8"))
    for item in estado["documentos"]:
        assert conferir_documento(storage, item["doc"]) == item["hashes"]
    doc = estado["documentos"][0]["doc"]
    assert pedir(json={"documento_id": doc["documento_id"], "tipo_arquivo": "TEXTO",
                      "documento_texto": "Duplicado após reinício", "canal_origem": "Recepcao"}).status_code == 409
    historico = requests.get(API + "/historico", timeout=120)
    historico.raise_for_status()
    assert len([d for d in historico.json() if d["documento_id"] == doc["documento_id"]]) == 2
    atual = snapshot(storage)
    assert all(atual.get(chave) == etag for chave, etag in estado["baseline"].items())
    estado["checks"].append("reinicio_409_historico_e_hashes_preservados")
    estado["aguardando_reinicio"] = False
    estado["concluido_em"] = datetime.now(timezone.utc).isoformat()
    salvar("estado.json", estado)
    print("FASE 2 OK: persistência, histórico e 409 após reinício confirmados.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("acao", choices=["preflight", "executar", "conferir"])
    acao = parser.parse_args().acao
    {"preflight": preflight, "executar": executar, "conferir": conferir}[acao]()
