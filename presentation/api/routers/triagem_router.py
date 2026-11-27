"""
Roteador de Apresentação: API REST de Triagem Clínica e Auditoria
Gerencia a ingestão documental, listagem das filas do OCI e homologação Human-in-the-Loop.
"""

import base64
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from application.dtos.input_request import TipoArquivoEnum, TriagemRequestDTO
from application.dtos.output_response import TriagemResponseDTO
from application.use_cases.processar_triagem import ProcessarTriagemUseCase
from application.use_cases.acompanhar_fluxo import concluir_homologacao
from application.use_cases.identidade_documento import identificar_relatorio, caminho_execucao, identidade_execucao, identidade
from application.use_cases.homologacao import (
    PREFIXO_DECISOES, PREFIXO_CONCLUIDAS, chave_conclusao, chave_decisao,
)
from domain.exceptions import DocumentoJaExiste
from infrastructure.oci_client.client_factory import get_triagem_use_case

logger = logging.getLogger("MediFlowAuditoria")


def _erro_inesperado_triagem(operacao: str, exc: Exception) -> HTTPException:
    """Padroniza erro HTTP 500 com identificador de correlação sem expor detalhes internos."""
    referencia = uuid4().hex[:12]
    logger.error("Falha inesperada ao %s [ref=%s] (%s).", operacao, referencia, type(exc).__name__)
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Erro inesperado ao {operacao}. Informe a referência {referencia} para suporte.",
    )

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


class ReprocessamentoDTO(BaseModel):
    documento_id: str
    origem_oci_path: str
    canal_origem: str = Field(..., min_length=1)


@router.post(
    "/reprocessar",
    response_model=TriagemResponseDTO,
    responses={409: {"description": "Original indisponível ou sem referência válida; o reprocessamento não foi iniciado."}},
)
def reprocessar_documento(payload: ReprocessamentoDTO, use_case=Depends(get_triagem_use_case)):
    try:
        caminho = payload.origem_oci_path
        if not caminho.startswith(("processados/", "auditoria_humana/", "fluxo/")) or ".." in caminho.split("/"):
            raise HTTPException(422, "Selecione um relatório ou acompanhamento existente.")
        anterior = use_case.storage.obter_json(use_case.bucket_name, caminho)
        if not anterior:
            raise HTTPException(404, "Execução anterior não localizada.")
        if anterior.get("documento_id") != payload.documento_id:
            raise HTTPException(422, "O identificador não corresponde à execução selecionada.")
        doc = anterior.get("documento") or anterior
        bruto = doc.get("armazenamento_oci", {}).get("caminho_documento_bruto") or anterior.get("caminho_documento_bruto")
        if not bruto or not bruto.startswith("recebidos/") or ".." in bruto.split("/"):
            raise HTTPException(409, "Execução sem referência válida ao original; reprocessamento indisponível.")
        conteudo = use_case.storage.obter_arquivo(use_case.bucket_name, bruto)
        if not conteudo:
            raise HTTPException(409, "Original indisponível; verifique versões ou cópias antes de reprocessar.")
        tipo = doc.get("tipo_arquivo") or anterior.get("tipo_arquivo") or ("PDF" if bruto.endswith(".pdf") else "IMAGEM" if bruto.endswith((".jpg", ".jpeg", ".png")) else "TEXTO")
        request = TriagemRequestDTO(documento_id=payload.documento_id, tipo_arquivo=tipo,
            arquivo_base64=base64.b64encode(conteudo).decode("ascii"), canal_origem=payload.canal_origem)
    except HTTPException:
        raise
    except Exception as exc:
        raise _erro_inesperado_triagem("reprocessar o documento", exc) from exc

    try:
        execucao_anterior = identidade_execucao(anterior, caminho)
        return use_case.executar(request, reprocessamento_de=caminho, execucao_anterior_id=execucao_anterior)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise _erro_inesperado_triagem("reprocessar o documento", exc) from exc


# -------------------------------------------------------------------------
# 1. Endpoints de Ingestão e Processamento
# -------------------------------------------------------------------------

@router.post(
    "",
    response_model=TriagemResponseDTO,
    status_code=status.HTTP_200_OK,
    summary="Processar e triar documento clínico via JSON",
    description="Recebe carga estruturada (JSON/Base64), executa o grafo condicional e persiste no OCI.",
    responses={409: {"description": "documento_id já cadastrado; nenhum original, inferência ou alerta é gravado."}},
)
def processar_documento_json(
    request: TriagemRequestDTO,
    use_case: ProcessarTriagemUseCase = Depends(get_triagem_use_case)
) -> TriagemResponseDTO:
    """Endpoint primário de triagem automatizada via requisição JSON estruturada."""
    try:
        return use_case.executar(request)
    except DocumentoJaExiste as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as ve:
        raise HTTPException(
            # Literal: a constante mudou de nome entre versões do Starlette.
            status_code=422,
            detail=f"Inconsistência cadastral ou clínica: {str(ve)}"
        )
    except Exception as exc:
        raise _erro_inesperado_triagem("processar a triagem", exc) from exc


@router.post(
    "/upload",
    response_model=TriagemResponseDTO,
    status_code=status.HTTP_200_OK,
    summary="Upload direto de arquivo (PDF / Imagem / TXT / JSON)",
    description="Recebe arquivo binário via multipart/form-data e executa a triagem multimodal.",
    responses={409: {"description": "documento_id já cadastrado; nenhum original, inferência ou alerta é gravado."}},
)
async def processar_documento_upload(
    documento_id: str = Form(..., description="ID do documento (ex: DOC-CLIN-2026-8942)"),
    canal_origem: str = Form(..., description="Canal de entrada (ex: Pronto_Socorro, Ambulatorio)"),
    arquivo: UploadFile = File(..., description="Documento PDF, PNG, JPG, TXT ou JSON em UTF-8 (BOM opcional)"),
    use_case: ProcessarTriagemUseCase = Depends(get_triagem_use_case)
) -> TriagemResponseDTO:
    """Endpoint para upload de arquivos brutos via formulário multipart."""
    try:
        conteudo_bytes = await arquivo.read()
    except Exception as exc:
        raise _erro_inesperado_triagem("processar o arquivo enviado", exc) from exc
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
    elif nome_arquivo.endswith(".json") or content_type.split(";")[0].strip() == "application/json":
        tipo_enum = TipoArquivoEnum.JSON
    elif nome_arquivo.endswith(".txt") or content_type.split(";")[0].strip() == "text/plain":
        tipo_enum = TipoArquivoEnum.TEXTO
    else:
        raise HTTPException(415, "Formato não suportado. Envie PDF, PNG, JPG, TXT ou JSON em UTF-8.")

    b64_conteudo = base64.b64encode(conteudo_bytes).decode("utf-8")

    dto_entrada = TriagemRequestDTO(
        documento_id=documento_id,
        tipo_arquivo=tipo_enum,
        documento_texto=None,
        arquivo_base64=b64_conteudo,
        canal_origem=canal_origem,
    )

    try:
        return await run_in_threadpool(use_case.executar, dto_entrada)
    except DocumentoJaExiste as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise _erro_inesperado_triagem("processar o arquivo enviado", exc) from exc


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
                casos.append(identificar_relatorio(doc, chave))
    # Um urgente com pendências mantém um único registro na auditoria.
    for chave in use_case.storage.listar_objetos_por_prefixo(use_case.bucket_name, "auditoria_humana/"):
        if chave.endswith(".json") and not use_case.storage.obter_json(use_case.bucket_name, chave_decisao(chave)):
            doc = use_case.storage.obter_json(use_case.bucket_name, chave)
            if doc and doc.get("decisao_roteamento", {}).get("destino_principal") == "Fila_Emergencia_Medica":
                casos.append(identificar_relatorio(doc, chave))
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
        if chave.endswith(".json") and not use_case.storage.obter_json(use_case.bucket_name, chave_decisao(chave)):
            doc = use_case.storage.obter_json(use_case.bucket_name, chave)
            if doc:
                pendencias.append(identificar_relatorio(doc, chave))
    return pendencias


# -------------------------------------------------------------------------
# 3. Endpoint de Homologação Human-in-the-Loop
# -------------------------------------------------------------------------

@router.post(
    "/homologar",
    status_code=status.HTTP_200_OK,
    summary="Homologar decisão de auditoria humana",
    responses={202: {"description": "Decisão registrada com finalização pendente."},
               409: {"description": "A pendência já possui uma decisão ou relatório final."}},
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
    storage, bucket = use_case.storage, use_case.bucket_name
    origem = payload.origem_oci_path
    chave = chave_decisao(origem)
    decisao = storage.obter_json(bucket, chave)
    if decisao is None:
        documento = storage.obter_json(bucket, origem)
        if documento is None:
            # A origem pode ter sido removida logo após outra requisição decidir.
            decisao = storage.obter_json(bucket, chave)
            if decisao is None:
                raise HTTPException(404, "Pendência de auditoria não localizada.")
        else:
            if documento.get("documento_id") != payload.documento_id:
                raise HTTPException(422, "O identificador não corresponde ao documento em revisão.")
            proposta = _preparar_homologacao(payload, documento)
            caminho = caminho_execucao(payload.documento_id, proposta["documento"]["execucao_id"])
            ja_processado = any(
                storage.obter_json(bucket, f"processados/{pasta}/{caminho}.json") is not None
                for pasta in ("rotina", "urgentes", "rejeitados")
            )
            if not ja_processado and storage.criar_json_exclusivo(bucket, chave, proposta):
                decisao = proposta
            else:
                decisao = storage.obter_json(bucket, chave)
                if decisao is None:
                    if ja_processado:
                        raise HTTPException(409, "A execução já tem um relatório final. Verifique a pendência anterior.")
                    raise HTTPException(409, "Outra solicitação está registrando a decisão desta pendência.")
    if decisao["solicitacao"] != payload.model_dump():
        raise HTTPException(409, "Já existe uma decisão registrada para esta pendência.")
    return _finalizar_homologacao(use_case, decisao)


def _preparar_homologacao(payload, doc_antigo):
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

        pasta = f"processados/{subpasta}"

    else:
        # Fluxo de rejeição
        pasta = "processados/rejeitados"
        doc_antigo["status"] = "erro"
        doc_antigo.setdefault("decisao_roteamento", {})
        doc_antigo["decisao_roteamento"]["requer_auditoria_humana"] = False
        doc_antigo["decisao_roteamento"]["justificativa_roteamento"] = (
            f"Documento rejeitado em auditoria humana: {payload.parecer_auditor}"
        )

    # A chave de origem distingue legados que compartilham execucao_id.
    execucao = identidade_execucao(doc_antigo, payload.origem_oci_path)
    if doc_antigo.get("execucao_id") and doc_antigo["execucao_id"] != execucao:
        doc_antigo["execucao_legada_id"] = doc_antigo["execucao_id"]
    doc_antigo["execucao_id"] = execucao
    novo_caminho = f"{pasta}/{caminho_execucao(payload.documento_id, execucao)}.json"
    doc_antigo.setdefault("armazenamento_oci", {})
    doc_antigo["armazenamento_oci"]["caminho_objeto"] = novo_caminho
    doc_antigo["armazenamento_oci"]["status_backup"] = "sucesso"

    doc_antigo["homologado_em"] = datetime.now(timezone.utc).isoformat()
    return {"solicitacao": payload.model_dump(), "documento": doc_antigo, "destino": novo_caminho}


def _finalizar_homologacao(use_case, decisao):
    storage, bucket = use_case.storage, use_case.bucket_name
    solicitacao = decisao["solicitacao"]
    documento = decisao["documento"]
    origem = solicitacao["origem_oci_path"]
    destino = decisao["destino"]
    aprovado = solicitacao["decisao"] == "aprovar"
    resposta = {
        "status": "sucesso",
        "documento_id": solicitacao["documento_id"],
        "destino_aprovado": solicitacao["destino_aprovado"] if aprovado else "Rejeitado",
        "caminho_novo_oci": destino,
        "notificacao_enviada": None,
        "acompanhamento_fluxo_confirmado": True,
    }
    try:
        conclusao = storage.obter_json(bucket, chave_conclusao(origem))
        if conclusao is None:
            if not storage.mover_objeto(bucket, origem, destino, documento):
                raise RuntimeError("Falha ao movimentar o relatório.")
            concluir_homologacao(storage, bucket, documento, aprovado, origem=origem)
            if not storage.salvar_json(bucket, chave_conclusao(origem), {"concluida": True}):
                raise RuntimeError("Falha ao confirmar a homologação.")
    except Exception:
        logger.exception("Homologação registrada, com finalização pendente para %s", resposta["documento_id"])
        resposta.update(status="pendente", acompanhamento_fluxo_confirmado=False)
        return JSONResponse(status_code=202, content=resposta)
    if aprovado and solicitacao["destino_aprovado"] == "Fila_Emergencia_Medica":
        alerta = documento["decisao_roteamento"]["notificacao_gerada"]
        resposta["notificacao_enviada"] = _notificar_homologacao(use_case, origem, alerta)
    return resposta


def _notificar_homologacao(use_case, origem, alerta):
    storage, bucket = use_case.storage, use_case.bucket_name
    chave = f"homologacoes/alertas/{identidade(origem)}.json"
    # A reserva impede reenvio inclusive quando a entrega anterior é inconclusiva.
    try:
        if not storage.criar_json_exclusivo(bucket, chave, {"enviada": None}):
            registro = storage.obter_json(bucket, chave) or {}
            return registro.get("enviada")
        try:
            enviada = bool(use_case.notifier.enviar_alerta_urgencia(**alerta))
        except Exception:
            logger.exception("Falha ao enviar alerta de homologação.")
            enviada = False
        if not storage.salvar_json(bucket, chave, {"enviada": enviada}):
            logger.error("Não foi possível confirmar o resultado do alerta de homologação.")
        return enviada
    except Exception:
        logger.exception("Não foi possível confirmar o alerta de homologação.")
        return None


class RetomadaHomologacaoDTO(BaseModel):
    documento_id: str
    origem_oci_path: str


@router.get("/homologacoes/pendentes")
def listar_homologacoes_pendentes(use_case=Depends(get_triagem_use_case)):
    storage, bucket = use_case.storage, use_case.bucket_name
    concluidas = {
        chave.removeprefix(PREFIXO_CONCLUIDAS)
        for chave in storage.listar_objetos_por_prefixo(bucket, PREFIXO_CONCLUIDAS)
    }
    pendentes = []
    for chave in storage.listar_objetos_por_prefixo(bucket, PREFIXO_DECISOES):
        if chave.removeprefix(PREFIXO_DECISOES) not in concluidas:
            decisao = storage.obter_json(bucket, chave)
            if decisao:
                solicitacao = decisao["solicitacao"]
                pendentes.append({campo: solicitacao[campo] for campo in ("documento_id", "origem_oci_path")})
    return pendentes


@router.post("/homologacoes/retomar")
def retomar_homologacao(payload: RetomadaHomologacaoDTO, use_case=Depends(get_triagem_use_case)):
    decisao = use_case.storage.obter_json(use_case.bucket_name, chave_decisao(payload.origem_oci_path))
    if not decisao or decisao["solicitacao"]["documento_id"] != payload.documento_id:
        raise HTTPException(404, "Decisão registrada não localizada.")
    return _finalizar_homologacao(use_case, decisao)
