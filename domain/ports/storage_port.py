# domain/ports/storage_port.py
from abc import ABC, abstractmethod
from typing import Any, Union, Dict, List

class StoragePort(ABC):
    """Contrato de armazenamento de documentos, independente do provedor."""

    def criar_json_exclusivo(self, bucket_name: str, object_name: str, json_data: dict) -> bool:
        """Cria atomicamente; False somente se já existe. Nunca sobrescreve."""
        raise NotImplementedError("O armazenamento precisa suportar criação atômica.")

    def obter_arquivo(self, bucket_name: str, object_name: str) -> bytes | None:
        """Recupera o original quando suportado pelo adaptador."""
        raise NotImplementedError

    @abstractmethod
    def obter_json(self, bucket_name: str, object_name: str):
        """Recupera o relatório ou retorna None quando ausente."""

    @abstractmethod
    def listar_objetos_por_prefixo(self, bucket_name: str, prefixo: str) -> list[str]:
        """Lista os objetos do bucket sob o prefixo solicitado."""

    @abstractmethod
    def mover_objeto(self, bucket_name: str, origem: str, destino: str, novos_dados=None) -> bool:
        """Persiste no destino e remove a origem apenas após sucesso."""

    @abstractmethod
    def salvar_arquivo(self, bucket_name: str, object_name: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        """Persiste um objeto e retorna o caminho/URI de confirmação."""
        pass

    @abstractmethod
    def salvar_json(self, bucket_name: str, object_name: str, json_data: Union[Dict[str, Any], List[Any], str]) -> bool:
        """Salva metadados e decisões estruturadas na pasta de status apropriada."""
        pass
