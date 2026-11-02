"""Armazenamento efêmero de desenvolvimento, sem dependência do SDK OCI."""
import json
from threading import RLock

from domain.ports.storage_port import StoragePort


class MemoryStorageAdapter(StoragePort):
    modo = "simulado"
    simulado = True

    def __init__(self):
        self.objetos = {}
        self._lock = RLock()

    def criar_json_exclusivo(self, bucket_name, object_name, json_data):
        with self._lock:
            if (bucket_name, object_name) in self.objetos:
                return False
            if not self.salvar_json(bucket_name, object_name, json_data):
                raise RuntimeError("Não foi possível reservar o cadastro.")
            return True

    def salvar_arquivo(self, bucket_name, object_name, data, content_type="application/octet-stream"):
        self.objetos[(bucket_name, object_name)] = bytes(data)
        return object_name

    def salvar_json(self, bucket_name, object_name, json_data):
        payload = json.dumps(json_data, ensure_ascii=False).encode("utf-8") if isinstance(json_data, (dict, list)) else str(json_data).encode("utf-8")
        self.salvar_arquivo(bucket_name, object_name, payload)
        return True

    def obter_arquivo(self, bucket_name, object_name):
        return self.objetos.get((bucket_name, object_name))

    def obter_json(self, bucket_name, object_name):
        bruto = self.obter_arquivo(bucket_name, object_name)
        return json.loads(bruto) if bruto is not None else None

    def listar_objetos_por_prefixo(self, bucket_name, prefixo):
        return sorted(chave for bucket, chave in list(self.objetos) if bucket == bucket_name and chave.startswith(prefixo))

    def mover_objeto(self, bucket_name, origem, destino, novos_dados=None):
        dados = novos_dados if novos_dados is not None else self.obter_json(bucket_name, origem)
        if dados is None:
            return False
        self.salvar_json(bucket_name, destino, dados)
        if origem != destino:
            self.objetos.pop((bucket_name, origem), None)
        return True
