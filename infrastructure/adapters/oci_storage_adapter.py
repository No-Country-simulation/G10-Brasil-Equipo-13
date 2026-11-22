"""Adaptador OCI nativo, compartilhado entre a nuvem e o emulador local."""
import json
import os
import tempfile
from pathlib import Path

import oci

from domain.ports.storage_port import StoragePort


class OCIStorageAdapter(StoragePort):
    modo = "oci"
    simulado = False

    def __init__(self, config_dict, namespace_name, service_endpoint=None, reservas_db=None):
        self.namespace = namespace_name
        self.reservas = None
        if service_endpoint is not None:
            from infrastructure.adapters.sqlite_reservas import SqliteReservas
            caminho = reservas_db or os.getenv("MEDIFLOW_RESERVAS_DB") or Path(tempfile.gettempdir()) / "mediflow-reservas.sqlite3"
            self.reservas = SqliteReservas(caminho)
        self.client = oci.object_storage.ObjectStorageClient(
            config_dict, service_endpoint=service_endpoint, timeout=(5, 15),
            retry_strategy=oci.retry.NoneRetryStrategy(),
        )

    def garantir_bucket(self, bucket_name, compartment_id):
        """Inicialização idempotente usada somente no ambiente emulado."""
        try:
            self.client.get_bucket(self.namespace, bucket_name)
        except oci.exceptions.ServiceError as exc:
            if exc.status != 404:
                raise
            try:
                self.client.create_bucket(self.namespace, oci.object_storage.models.CreateBucketDetails(
                    name=bucket_name, compartment_id=compartment_id,
                ))
            except oci.exceptions.ServiceError as conflito:
                if conflito.status != 409:
                    raise
                self.client.get_bucket(self.namespace, bucket_name)

    def salvar_arquivo(self, bucket_name, object_name, data, content_type="application/octet-stream"):
        self.client.put_object(
            namespace_name=self.namespace, bucket_name=bucket_name,
            object_name=object_name, put_object_body=bytes(data), content_type=content_type,
        )
        return f"{self.namespace}/{bucket_name}/{object_name}"

    def salvar_json(self, bucket_name, object_name, json_data):
        payload = json.dumps(json_data, ensure_ascii=False).encode("utf-8") if isinstance(json_data, (dict, list)) else str(json_data).encode("utf-8")
        self.salvar_arquivo(bucket_name, object_name, payload, "application/json; charset=utf-8")
        return True

    def criar_json_exclusivo(self, bucket_name, object_name, json_data):
        # No emulador, a restrição SQL é compartilhada entre processos.
        if self.reservas and not self.reservas.criar(self.namespace, bucket_name, object_name):
            return False
        # SDK OCI put_object: '*' é o único valor válido de if_none_match.
        # Não há fallback para escrita incondicional se o serviço não suportar.
        try:
            self.client.put_object(
                namespace_name=self.namespace, bucket_name=bucket_name,
                object_name=object_name,
                put_object_body=json.dumps(json_data, ensure_ascii=False).encode("utf-8"),
                content_type="application/json; charset=utf-8", if_none_match="*",
            )
        except oci.exceptions.ServiceError as exc:
            if exc.status == 412:
                return False
            raise
        return True

    def cancelar_cadastro(self, bucket_name, cadastro, fluxo, execucao_id):
        def cancelar():
            try:
                resposta = self.client.get_object(self.namespace, bucket_name, cadastro)
                reserva = json.loads(resposta.data.content)
                etag = resposta.headers.get("etag")
                if reserva.get("primeira_execucao_id") != execucao_id or not etag:
                    return False
                # A versão lida deve continuar atual no instante da exclusão.
                self.client.delete_object(self.namespace, bucket_name, cadastro, if_match=etag)
            except oci.exceptions.ServiceError as exc:
                if exc.status in (404, 412):
                    return False
                raise
            # O histórico de falha já está arquivado; nunca apagar outro fluxo.
            try:
                self.client.delete_object(self.namespace, bucket_name, fluxo)
            except oci.exceptions.ServiceError as exc:
                if exc.status != 404:
                    raise
            return True

        if self.reservas:
            return self.reservas.cancelar_se(self.namespace, bucket_name, cadastro, cancelar)
        return cancelar()

    def obter_arquivo(self, bucket_name, object_name):
        try:
            return self.client.get_object(
                namespace_name=self.namespace, bucket_name=bucket_name,
                object_name=object_name,
            ).data.content
        except oci.exceptions.ServiceError as exc:
            if exc.status == 404:
                return None
            raise

    def obter_json(self, bucket_name, object_name):
        bruto = self.obter_arquivo(bucket_name, object_name)
        return json.loads(bruto.decode("utf-8")) if bruto is not None else None

    def listar_objetos_por_prefixo(self, bucket_name, prefixo):
        chaves = []
        inicio = None
        while True:
            resposta = self.client.list_objects(
                namespace_name=self.namespace, bucket_name=bucket_name,
                prefix=prefixo, start=inicio,
            )
            chaves.extend(obj.name for obj in resposta.data.objects)
            inicio = resposta.data.next_start_with
            if not inicio:
                return chaves

    def mover_objeto(self, bucket_name, origem, destino, novos_dados=None):
        dados = novos_dados if novos_dados is not None else self.obter_json(bucket_name, origem)
        if dados is None:
            return False
        if not self.salvar_json(bucket_name, destino, dados):
            return False
        if origem != destino:
            try:
                self.client.delete_object(namespace_name=self.namespace, bucket_name=bucket_name, object_name=origem)
            except oci.exceptions.ServiceError as exc:
                if exc.status != 404:
                    raise
        return True
