import base64
import binascii
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class TipoArquivoEnum(str, Enum):
    PDF = "PDF"
    IMAGEM = "IMAGEM"
    JSON = "JSON"
    TEXTO = "TEXTO"


class TriagemRequestDTO(BaseModel):
    """Schema de entrada para requisição de processamento clínico."""
    documento_id: str = Field(
        ..., min_length=1,
        description="Identificador único do documento", 
        examples=["DOC-CLIN-2026-8942"]
    )
    tipo_arquivo: TipoArquivoEnum = Field(
        ..., 
        description="Formato do arquivo enviado"
    )
    documento_texto: Optional[str] = Field(
        None, 
        description="Conteúdo textual bruto extraído ou enviado diretamente"
    )
    arquivo_base64: Optional[str] = Field(
        None, 
        description="Arquivo em Base64: PDF, imagem ou TXT UTF-8 (BOM opcional)"
    )
    canal_origem: str = Field(
        ..., 
        description="Origem da solicitação", 
        examples=["Pronto_Socorro", "Ambulatorio", "Recepcao"]
    )

    def conteudo_para_extracao(self) -> Optional[str]:
        """Normaliza TXT codificado sem reinterpretar texto enviado literalmente."""
        if self.tipo_arquivo == TipoArquivoEnum.TEXTO and self.arquivo_base64:
            try:
                bruto = base64.b64decode(self.arquivo_base64, validate=True)
                texto = bruto.decode("utf-8-sig")
            except (binascii.Error, ValueError, UnicodeError) as exc:
                raise ValueError("TXT deve conter Base64 válido e texto UTF-8 (BOM opcional).") from exc
            if not texto.strip() or any(ord(c) < 32 and c not in "\n\r\t" for c in texto):
                raise ValueError("TXT vazio ou com conteúdo binário não permitido.")
            return texto
        return self.arquivo_base64 if self.arquivo_base64 else self.documento_texto
