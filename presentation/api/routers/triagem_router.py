"""
Roteador de Apresentação: API REST de Triagem Clínica e Auditoria
Gerencia a ingestão documental, listagem das filas do OCI e homologação Human-in-the-Loop.
"""

import base64
import logging
from typing import Any, Dict, List
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from application.dtos.input_request import TipoArquivoEnum, TriagemRequestDTO
from application.dtos.output_response import TriagemResponseDTO
from application.use_cases.processar_triagem import ProcessarTriagemUseCase
from application.use_cases.acompanhar_fluxo import concluir_homologacao
from infrastructure.oci_client.client_factory import get_triagem_use_case

logger = logging.getLogger("MediFlowAuditoria")

router = APIRouter(
    prefix="/triagem",
    tags=["Triagem Clínica & Filas"]
)


class HomologacaoAuditoriaDTO(BaseModel):
    """Schema para validação e despacho de documentos pelo auditor humano."""
    documento_id: str
    origem_oci_path: str = Field(..., examples=["auditoria_humana/DOC-CLIN-2026-8942.json"])
    paciente_nome: str
    crm_retificado: str
    diagnostico: str
    cid_homologado: str
    destino_aprovado: str = Field(
        ...,
        examples=[
            "Fila_Emergencia_Medica",
            "Prontuario_Eletronico_Paciente",
            "Farmacia_Hospitalar",
            "Auditoria_de_Autorizacoes",
        ]
    )
    parecer_auditor: str
    decisao: str = Field(..., pattern="^(aprovar|rejeitar)$", description="'aprovar' ou 'rejeitar'")


# -------------------------------------------------------------------------
# 1. Endpoints de Ingestão e Processamento
# -------------------------------------------------------------------------

@router.post(
    "",
    response_model=TriagemResponseDTO,
    status_code=status.HTTP_200_OK,
    summary="Processar e triar documento clínico via JSON",
    description="Recebe carga estruturada (JSON/Base64), executa o grafo condicional e persiste no OCI."
)
def processar_documento_json(
    request: TriagemRequestDTO,
    use_case: ProcessarTriagemUseCase = Depends(get_triagem_use_case)
) -> TriagemResponseDTO:
    """Endpoint primário de triagem automatizada via requisição JSON estruturada."""
    try:
        return use_case.executar(request)
    except ValueError as ve:
        raise HTTPException(
            # Literal: a constante mudou de nome entre versões do Starlette.
            status_code=422,
            detail=f"Inconsistência cadastral ou clínica: {str(ve)}"
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha na triagem do documento: {str(exc)}"
        )


@router.post(
    "/upload",
    response_model=TriagemResponseDTO,
    status_code=status.HTTP_200_OK,
    summary="Upload direto de arquivo (PDF / Imagem / TXT UTF-8)",
    description="Recebe arquivo binário via multipart/form-data e executa a triagem multimodal."
)
async def processar_documento_upload(
    documento_id: str = Form(..., description="ID do documento (ex: DOC-CLIN-2026-8942)"),
    canal_origem: str = Form(..., description="Canal de entrada (ex: Pronto_Socorro, Ambulatorio)"),
    arquivo: UploadFile = File(..., description="Documento PDF, PNG, JPG ou TXT UTF-8 (BOM opcional)"),
    use_case: ProcessarTriagemUseCase = Depends(get_triagem_use_case)
) -> TriagemResponseDTO:
    """Endpoint para upload de arquivos brutos via formulário multipart."""
    conteudo_bytes = await arquivo.read()
    if not conteudo_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O arquivo enviado está vazio."
        )

    content_type = (arquivo.content_type or "").lower()
    nome_arquivo = (arquivo.filename or "").lower()

    if "pdf" in content_type or nome_arquivo.endswith(".pdf"):
        tipo_enum = TipoArquivoEnum.PDF
    elif any(fmt in content_type for fmt in ["image", "jpeg", "jpg", "png"]) or any(
        nome_arquivo.endswith(ext) for ext in [".jpg", ".jpeg", ".png"]
    ):
        tipo_enum = TipoArquivoEnum.IMAGEM
    elif nome_arquivo.endswith(".txt") or content_type.split(";")[0].strip() == "text/plain":
        tipo_enum = TipoArquivoEnum.TEXTO
    else:
        raise HTTPException(415, "Formato não suportado. Envie PDF, PNG, JPG ou TXT UTF-8.")

    b64_conteudo = base64.b64encode(conteudo_bytes).decode("utf-8")

    dto_entrada = TriagemRequestDTO(
        documento_id=documento_id,
        tipo_arquivo=tipo_enum,
        documento_texto=None,
        arquivo_base64=b64_conteudo,
        canal_origem=canal_origem,
    )

    try:
        dto_entrada.conteudo_para_extracao()
        return await run_in_threadpool(use_case.executar, dto_entrada)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao processar arquivo: {str(exc)}"
        )


# -------------------------------------------------------------------------
# 2. Endpoints de Consulta das Filas do OCI Object Storage
# -------------------------------------------------------------------------

@router.get(
    "/filas/urgencias",
    response_model=List[Dict[str, Any]],
    summary="Listar casos críticos de emergência",
    description="Recupera os JSONs persistidos sob o prefixo 'processados/urgentes/' no bucket OCI."
)
def listar_fila_urgencias(
    use_case: ProcessarTriagemUseCase = Depends(get_triagem_use_case)
) -> List[Dict[str, Any]]:
    """Consulta em tempo real os casos urgentes salvos no OCI Object Storage."""
    prefixo = "processados/urgentes/"
    chaves = use_case.storage.listar_objetos_por_prefixo(use_case.bucket_name, prefixo)
    casos: List[Dict[str, Any]] = []

    for chave in chaves:
        if chave.endswith(".json"):
            doc = use_case.storage.obter_json(use_case.bucket_name, chave)
            if doc:
                casos.append(doc)
    # Um urgente com pendências mantém um único registro na auditoria.
    for chave in use_case.storage.listar_objetos_por_prefixo(use_case.bucket_name, "auditoria_humana/"):
        if chave.endswith(".json"):
            doc = use_case.storage.obter_json(use_case.bucket_name, chave)
            if doc and doc.get("decisao_roteamento", {}).get("destino_principal") == "Fila_Emergencia_Medica":
                casos.append(doc)
    return casos


@router.get(
    "/filas/auditoria",
    response_model=List[Dict[str, Any]],
    summary="Listar pendências de auditoria humana",
    description="Recupera os documentos retidos no prefixo 'auditoria_humana/' no bucket OCI."
)
def listar_fila_auditoria(
    use_case: ProcessarTriagemUseCase = Depends(get_triagem_use_case)
) -> List[Dict[str, Any]]:
    """Consulta as pendências com score baixo ou conflitos para revisão humana."""
    prefixo = "auditoria_humana/"
    chaves = use_case.storage.listar_objetos_por_prefixo(use_case.bucket_name, prefixo)
    pendencias: List[Dict[str, Any]] = []

    for chave in chaves:
        if chave.endswith(".json"):
            doc = use_case.storage.obter_json(use_case.bucket_name, chave)
            if doc:
                pendencias.append(doc)
    return pendencias


# -------------------------------------------------------------------------
# 3. Endpoint de Homologação Human-in-the-Loop
# -------------------------------------------------------------------------

@router.post(
    "/homologar",
    status_code=status.HTTP_200_OK,
    summary="Homologar decisão de auditoria humana",
    description="Retifica dados, destrava a contingência e move o registro no OCI conforme a criticidade."
)
def homologar_documento_auditoria(
    payload: HomologacaoAuditoriaDTO,
    use_case: ProcessarTriagemUseCase = Depends(get_triagem_use_case)
) -> Dict[str, Any]:
    """
    Persiste a decisão do auditor no OCI Object Storage:
    - Se aprovado como emergência: move para 'processados/urgentes/'.
    - Se aprovado para rotina/outro setor: move para 'processados/rotina/'.
    - Se rejeitado: move para 'processados/rejeitados/'.
    """
    if not payload.origem_oci_path.startswith("auditoria_humana/") or ".." in payload.origem_oci_path.split("/"):
        raise HTTPException(422, "A origem deve ser uma pendência de auditoria humana.")
    doc_antigo = use_case.storage.obter_json(use_case.bucket_name, payload.origem_oci_path)
    if not doc_antigo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Documento pendente '{payload.origem_oci_path}' não foi localizado no OCI."
        )

    if doc_antigo.get("documento_id") != payload.documento_id:
        raise HTTPException(422, "O identificador não corresponde ao documento em revisão.")

    if payload.decisao == "aprovar":
        doc_antigo["status"] = "processado"
        # A falha original continua auditável; a revisão humana resolveu a pendência.
        if doc_antigo.get("erro_extracao"):
            doc_antigo["erro_extracao_anterior"] = doc_antigo.pop("erro_extracao")
        # Atualização das entidades clínicas retificadas
        doc_antigo.setdefault("dados_extraidos", {})
        doc_antigo["dados_extraidos"].setdefault("paciente", {})
        doc_antigo["dados_extraidos"].setdefault("medico_solicitante", {})

        doc_antigo["dados_extraidos"]["paciente"]["nome"] = payload.paciente_nome
        doc_antigo["dados_extraidos"]["medico_solicitante"]["crm"] = payload.crm_retificado
        doc_antigo["dados_extraidos"]["diagnostico_principal"] = payload.diagnostico
        doc_antigo["dados_extraidos"]["cid_sugerido"] = payload.cid_homologado

        doc_antigo.setdefault("decisao_roteamento", {})
        doc_antigo["decisao_roteamento"]["destino_principal"] = payload.destino_aprovado
        doc_antigo["decisao_roteamento"]["requer_auditoria_humana"] = False
        doc_antigo["decisao_roteamento"]["justificativa_roteamento"] = (
            f"Homologado e retificado por auditor humano: {payload.parecer_auditor}"
        )

        doc_antigo.setdefault("classificacao", {})

        # Direcionamento dinâmico conforme a gravidade aprovada
        if payload.destino_aprovado == "Fila_Emergencia_Medica":
            subpasta = "urgentes"
            doc_antigo["classificacao"]["nivel_prioridade"] = "Urgente"
            doc_antigo["decisao_roteamento"]["notificacao_gerada"] = {
                "canal": "Alerta_Plantao_Medico",
                "mensagem": f"ALERTA URGENTE: Paciente {payload.paciente_nome} despachado para emergência médica."
            }
        else:
            subpasta = "rotina"
            doc_antigo["classificacao"]["nivel_prioridade"] = "Rotina"
            doc_antigo["decisao_roteamento"]["notificacao_gerada"] = None

        novo_caminho = f"processados/{subpasta}/{payload.documento_id}.json"

    else:
        # Fluxo de rejeição
        novo_caminho = f"processados/rejeitados/{payload.documento_id}.json"
        doc_antigo["status"] = "erro"
        doc_antigo.setdefault("decisao_roteamento", {})
        doc_antigo["decisao_roteamento"]["requer_auditoria_humana"] = False
        doc_antigo["decisao_roteamento"]["justificativa_roteamento"] = (
            f"Documento rejeitado em auditoria humana: {payload.parecer_auditor}"
        )

    doc_antigo.setdefault("armazenamento_oci", {})
    doc_antigo["armazenamento_oci"]["caminho_objeto"] = novo_caminho
    doc_antigo["armazenamento_oci"]["status_backup"] = "sucesso"

    sucesso = use_case.storage.mover_objeto(
        bucket_name=use_case.bucket_name,
        origem=payload.origem_oci_path,
        destino=novo_caminho,
        novos_dados=doc_antigo,
    )

    if not sucesso:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Falha ao movimentar e persistir o registro no OCI Object Storage."
        )

    acompanhamento_confirmado = True
    try:
        concluir_homologacao(use_case.storage, use_case.bucket_name, doc_antigo, payload.decisao == "aprovar")
    except Exception:
        acompanhamento_confirmado = False
        logger.error("Decisão persistida, mas acompanhamento não confirmado para %s", payload.documento_id)

    notificacao_enviada = None
    if payload.decisao == "aprovar" and payload.destino_aprovado == "Fila_Emergencia_Medica":
        alerta = doc_antigo["decisao_roteamento"]["notificacao_gerada"]
        try:
            notificacao_enviada = bool(use_case.notifier.enviar_alerta_urgencia(
                canal=alerta["canal"], mensagem=alerta["mensagem"]
            ))
        except Exception:
            notificacao_enviada = False
            logger.exception("Falha ao notificar homologação urgente de %s", payload.documento_id)
        if not notificacao_enviada:
            logger.error("Homologação de %s persistida, mas o notificador falhou", payload.documento_id)

    return {
        "status": "sucesso",
        "documento_id": payload.documento_id,
        "destino_aprovado": payload.destino_aprovado if payload.decisao == "aprovar" else "Rejeitado",
        "caminho_novo_oci": novo_caminho,
        "notificacao_enviada": notificacao_enviada,
        "acompanhamento_fluxo_confirmado": acompanhamento_confirmado,
    }
