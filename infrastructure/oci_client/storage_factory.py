"""Composição dos adaptadores: memória, OCI emulado e OCI real."""
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

import oci
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from config.settings import settings
from infrastructure.adapters.memory_storage_adapter import MemoryStorageAdapter
from infrastructure.adapters.oci_storage_adapter import OCIStorageAdapter

LOCAL_TENANCY = "ocid1.tenancy.oc1..flocilocaltenancy0000000000000000000000000000000000000000"


def criar_config_emulador(endpoint):
    url = urlsplit(endpoint)
    if url.scheme != "http" or url.hostname not in {"localhost", "127.0.0.1", "::1", "oci-emulator", "host.docker.internal"} or url.username or url.password:
        raise ValueError("O endpoint emulado deve ser HTTP em um endereço local autorizado.")
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return {
        "user": "ocid1.user.oc1..mediflowlocaluser",
        "tenancy": LOCAL_TENANCY,
        "fingerprint": "aa:bb:cc:dd:ee:ff:00:11:22:33:44:55:66:77:88:99",
        "region": "us-ashburn-1",
        "key_content": chave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode(),
    }


@lru_cache()
def get_storage_adapter():
    if settings.STORAGE_MODE == "memory":
        return MemoryStorageAdapter()
    if settings.STORAGE_MODE == "emulator":
        config = criar_config_emulador(settings.OCI_SERVICE_ENDPOINT)
        storage = OCIStorageAdapter(config, settings.OCI_NAMESPACE, service_endpoint=settings.OCI_SERVICE_ENDPOINT,
            reservas_db=settings.MEDIFLOW_RESERVAS_DB or None)
        storage.modo = "emulador_oci"
        # O namespace do emulador pertence à tenancy local e pode ser derivado por ele.
        storage.namespace = storage.client.get_namespace().data
        storage.garantir_bucket(settings.OCI_BUCKET_NAME, LOCAL_TENANCY)
        return storage
    # Credenciais inválidas na nuvem nunca ativam memória silenciosamente.
    config = oci.config.from_file(str(Path(settings.OCI_CONFIG_FILE).expanduser()), settings.OCI_CONFIG_PROFILE)
    return OCIStorageAdapter(config, settings.OCI_NAMESPACE)
