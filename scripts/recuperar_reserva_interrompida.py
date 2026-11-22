"""Recupera uma reserva interrompida com os processos de triagem parados."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from application.use_cases.acompanhar_fluxo import chave_fluxo
from application.use_cases.identidade_documento import caminho_execucao, chave_cadastro, documento_legado_existe, identidade
from config.settings import settings
from infrastructure.oci_client.storage_factory import get_storage_adapter


def recuperar(storage, bucket, documento_id, execucao_id):
    cadastro = chave_cadastro(documento_id)
    reserva = storage.obter_json(bucket, cadastro)
    if reserva is None:
        # Um timeout inconclusivo pode deixar apenas o índice do emulador.
        if not storage.reservas:
            return False
        if documento_legado_existe(storage, bucket, documento_id):
            return False
        if storage.listar_objetos_por_prefixo(bucket, f"recebidos/{identidade(documento_id)}/"):
            return False
        return storage.reservas.cancelar_se(
            storage.namespace, bucket, cadastro,
            lambda: storage.obter_json(bucket, cadastro) is None,
        )
    if reserva.get("primeira_execucao_id") != execucao_id:
        return False

    caminho = caminho_execucao(documento_id, execucao_id)
    prefixo_original = f"recebidos/{caminho}."
    if storage.listar_objetos_por_prefixo(bucket, prefixo_original):
        return False

    for prefixo in ("processados/", "auditoria_humana/"):
        if any(chave.endswith(f"/{caminho}.json")
               for chave in storage.listar_objetos_por_prefixo(bucket, prefixo)):
            return False

    fluxo = chave_fluxo(documento_id, execucao_id)
    registro = storage.obter_json(bucket, fluxo)
    if registro and registro.get("etapa") not in ("recebidos", "falha"):
        return False

    tentativa = {
        **(registro or reserva),
        "documento_id": documento_id,
        "execucao_id": execucao_id,
        "recuperacao": "Reserva interrompida sem original, liberada em manutenção.",
    }
    if not storage.salvar_json(bucket, f"tentativas_interrompidas/{caminho}.json", tentativa):
        return False
    return storage.cancelar_cadastro(bucket, cadastro, fluxo, execucao_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("documento_id")
    parser.add_argument("execucao_id")
    parser.add_argument("--triagem-parada", action="store_true",
                        help="Confirma que todas as instâncias que escrevem no bucket estão paradas.")
    args = parser.parse_args()
    if not args.triagem_parada:
        parser.error("Pare todas as instâncias de triagem antes de recuperar a reserva.")
    storage = get_storage_adapter()
    if storage.modo not in ("oci", "emulador_oci"):
        parser.error("Configure o Object Storage usado pelo cadastro interrompido.")
    if not recuperar(storage, settings.OCI_BUCKET_NAME, args.documento_id, args.execucao_id):
        raise SystemExit("Reserva não liberada. Verifique a execução, o original e o acompanhamento.")
    print("Reserva liberada. O documento pode ser reenviado após reiniciar a API.")
