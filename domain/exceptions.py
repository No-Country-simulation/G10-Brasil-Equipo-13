"""Falhas técnicas de extração, sem conteúdo clínico ou credenciais."""


class FalhaExtracaoIA(RuntimeError):
    def __init__(self, codigo: str, mensagem: str):
        super().__init__(mensagem)
        self.codigo = codigo


class DocumentoJaExiste(RuntimeError):
    """Novo cadastro conflita com uma identidade já reservada."""
