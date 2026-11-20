from fastapi import FastAPI

from presentation.api.routers.triagem_router import router


def test_openapi_declara_409_nos_endpoints_de_cadastro():
    app = FastAPI()
    app.include_router(router)
    paths = app.openapi()["paths"]

    for caminho in ("/triagem", "/triagem/upload", "/triagem/reprocessar"):
        assert "409" in paths[caminho]["post"]["responses"], caminho
