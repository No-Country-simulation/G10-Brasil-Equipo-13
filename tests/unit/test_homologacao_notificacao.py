from unittest.mock import Mock

import pytest
from infrastructure.adapters.memory_storage_adapter import MemoryStorageAdapter

from presentation.api.routers.triagem_router import (
    HomologacaoAuditoriaDTO,
    homologar_documento_auditoria,
)


@pytest.mark.parametrize(
    "destino,decisao,persistido,retorno,excecao,esperado",
    [
        ("Fila_Emergencia_Medica", "aprovar", True, True, False, True),
        ("Fila_Emergencia_Medica", "aprovar", True, False, False, False),
        ("Fila_Emergencia_Medica", "aprovar", True, True, True, False),
        ("Farmacia_Hospitalar", "aprovar", True, True, False, None),
        ("Fila_Emergencia_Medica", "rejeitar", True, True, False, None),
        ("Fila_Emergencia_Medica", "aprovar", False, True, False, None),
    ],
)
def test_notificacao_apos_homologacao(destino, decisao, persistido, retorno, excecao, esperado):
    use_case = Mock(bucket_name="teste")
    storage = MemoryStorageAdapter()
    storage.salvar_json("teste", "auditoria_humana/TESTE.json", {"documento_id": "TESTE"})
    mover = Mock(wraps=storage.mover_objeto) if persistido else Mock(return_value=False)
    storage.mover_objeto = mover
    use_case.attach_mock(Mock(wraps=storage), "storage")
    use_case.notifier.enviar_alerta_urgencia.return_value = retorno
    if excecao:
        use_case.notifier.enviar_alerta_urgencia.side_effect = RuntimeError("falha simulada")
    payload = HomologacaoAuditoriaDTO(
        documento_id="TESTE", origem_oci_path="auditoria_humana/TESTE.json",
        paciente_nome="Paciente Teste", crm_retificado="12345-SP",
        diagnostico="Teste", cid_homologado="Z00", destino_aprovado=destino,
        parecer_auditor="Teste sintetico", decisao=decisao,
    )
    if not persistido:
        assert homologar_documento_auditoria(payload, use_case).status_code == 202
        use_case.notifier.enviar_alerta_urgencia.assert_not_called()
        return
    result = homologar_documento_auditoria(payload, use_case)
    repetido = homologar_documento_auditoria(payload, use_case)
    assert repetido == result
    mover.assert_called_once()
    assert result["notificacao_enviada"] is esperado
    if esperado is None:
        use_case.notifier.enviar_alerta_urgencia.assert_not_called()
    else:
        use_case.notifier.enviar_alerta_urgencia.assert_called_once_with(
            canal="Alerta_Plantao_Medico",
            mensagem="ALERTA URGENTE: Paciente Paciente Teste despachado para emergência médica.",
        )
        chamadas = [chamada[0] for chamada in use_case.mock_calls]
        assert chamadas.index("storage.mover_objeto") < chamadas.index("notifier.enviar_alerta_urgencia")
