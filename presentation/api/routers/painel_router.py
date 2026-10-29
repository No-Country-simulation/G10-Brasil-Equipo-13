"""Consultas do painel. Não realizam chamadas de inferência ou envio de alertas."""
from fastapi import APIRouter, Depends, HTTPException, Response

from infrastructure.oci_client.client_factory import get_triagem_use_case
from config.settings import settings
from application.use_cases.acompanhar_fluxo import consultar_fluxo
from application.use_cases.identidade_documento import identificar_relatorio

router = APIRouter(prefix="/triagem", tags=["Painel"])


@router.get("/armazenamento/objetos")
def listar_objetos_armazenados(use_case=Depends(get_triagem_use_case)):
    areas = {"recebidos/": "Documentos recebidos", "processados/": "Documentos processados", "auditoria_humana/": "Revisão humana", "fluxo/": "Acompanhamento interno"}
    objetos = []
    contagens = {}
    try:
        for prefixo, area in areas.items():
            chaves = sorted(set(use_case.storage.listar_objetos_por_prefixo(use_case.bucket_name, prefixo)))
            contagens[prefixo] = len(chaves)
            for chave in chaves:
                nome = chave.rsplit("/", 1)[-1]
                extensao = nome.rsplit(".", 1)[-1].upper() if "." in nome else "Não informado"
                objetos.append({"area": area, "nome": nome, "caminho": chave, "tipo": extensao, "estado": "Listado no armazenamento"})
    except Exception:
        raise HTTPException(503, "Não foi possível listar os objetos. Confira a conexão e as permissões do armazenamento.") from None
    return {"bucket": use_case.bucket_name, "modo": use_case.storage.modo, "contagens": contagens, "objetos": objetos}


@router.get("/diagnostico")
def consultar_diagnostico(conexoes: bool = False):
    # Funciona mesmo quando a inicialização dos adaptadores falha.
    from infrastructure.diagnostico import diagnosticar
    return diagnosticar(conexoes)


@router.get("/filas/processamento")
def listar_filas_processamento(use_case=Depends(get_triagem_use_case)):
    return consultar_fluxo(use_case.storage, use_case.bucket_name)


@router.get("/integracoes")
def consultar_integracoes(use_case=Depends(get_triagem_use_case)):
    return {
        "apresentacao": {"ativa": settings.APP_MODE == "presentation", "llm_real": settings.PRESENTATION_USE_LLM},
        "armazenamento": {
            "modo": use_case.storage.modo,
            "bucket": use_case.bucket_name,
            "conexao": "não verificada",
            "namespace": getattr(use_case.storage, "namespace", None),
        },
        "ia": {"provedor": "Simulação de apresentação" if settings.APP_MODE == "presentation" and not settings.PRESENTATION_USE_LLM else "Google Gemini", "modelo": "Respostas predefinidas" if settings.APP_MODE == "presentation" and not settings.PRESENTATION_USE_LLM else settings.GEMINI_MODEL_NAME, "conexao": "não se aplica" if settings.APP_MODE == "presentation" and not settings.PRESENTATION_USE_LLM else "não verificada"},
        "alertas": {
            "modo": "webhook" if use_case.notifier.webhook_url else "somente_log",
            "entrega": "não verificada",
        },
    }


@router.get("/historico")
def listar_historico(use_case=Depends(get_triagem_use_case)):
    documentos = []
    for prefixo in ("processados/", "auditoria_humana/"):
        for chave in use_case.storage.listar_objetos_por_prefixo(use_case.bucket_name, prefixo):
            if chave.endswith(".json"):
                doc = use_case.storage.obter_json(use_case.bucket_name, chave)
                if doc:
                    documentos.append(identificar_relatorio(doc, chave))
    return documentos


@router.get("/original")
def obter_original(caminho: str, use_case=Depends(get_triagem_use_case)):
    if not caminho.startswith("recebidos/") or ".." in caminho.split("/"):
        raise HTTPException(422, "Caminho de documento original inválido.")
    conteudo = use_case.storage.obter_arquivo(use_case.bucket_name, caminho)
    if conteudo is None:
        raise HTTPException(404, "Documento original não disponível.")
    tipo = "application/octet-stream"
    if conteudo.startswith(b"%PDF"):
        tipo = "application/pdf"
    elif conteudo.startswith(b"\x89PNG"):
        tipo = "image/png"
    elif conteudo.startswith(b"\xff\xd8"):
        tipo = "image/jpeg"
    elif caminho.endswith((".txt", ".json")):
        tipo = "text/plain; charset=utf-8"
    return Response(conteudo, media_type=tipo, headers={"Cache-Control": "no-store"})
