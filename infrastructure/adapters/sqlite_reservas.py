"""Índice transacional para reservas no emulador OCI local.

Floci 0.5.0 pode aceitar dois PUTs condicionais concorrentes. Todos os
trabalhadores emulados devem compartilhar este arquivo em volume persistente.
A OCI real usa diretamente a precondição atômica do serviço.
"""
import sqlite3
from pathlib import Path


class SqliteReservas:
    def __init__(self, caminho):
        self.caminho = str(caminho)
        Path(caminho).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.caminho, timeout=30) as conexao:
            conexao.execute("CREATE TABLE IF NOT EXISTS reservas (namespace TEXT NOT NULL, bucket TEXT NOT NULL, objeto TEXT NOT NULL, PRIMARY KEY (namespace, bucket, objeto))")

    def criar(self, namespace, bucket, objeto):
        with sqlite3.connect(self.caminho, timeout=30) as conexao:
            cursor = conexao.execute("INSERT INTO reservas VALUES (?, ?, ?) ON CONFLICT DO NOTHING", (namespace, bucket, objeto))
            return cursor.rowcount == 1
