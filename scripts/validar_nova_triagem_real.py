"""AppTest da Nova triagem contra API, Gemini e OCI reais de homologação.

Somente o seletor de arquivo recebe bytes sintéticos por injeção; o cliente
HTTP, a API, a IA e o armazenamento não são simulados. Não substitui QA visual.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests
from streamlit.testing.v1 import AppTest


def main():
    api = os.environ.get("API_URL", "")
    assert api == "http://api:8000/triagem", "Execute somente no UI isolado"
    r = requests.get(api + "/integracoes", timeout=60)
    r.raise_for_status()
    info = r.json()
    assert info["armazenamento"]["bucket"] == "mediflow-testes"
    assert info["armazenamento"]["modo"] == "oci"
    texto = Path("presentation_examples/rotina.txt").read_text(encoding="utf-8")
    bruto = json.dumps({"documento_texto": texto}, ensure_ascii=False).encode("utf-8-sig")
    arquivo = SimpleNamespace(name="rotina.json", getvalue=lambda: bruto)
    doc_id = "E2E-UI-" + uuid4().hex[:16]
    with patch("streamlit.file_uploader", return_value=arquivo):
        app = AppTest.from_file(Path(__file__).resolve().parents[1] / "presentation/web/app.py", default_timeout=180).run()
        app.switch_page("app_pages/nova_triagem.py").run()
        assert not app.exception
        app.text_input(key="novo_documento_id").set_value(doc_id)
        next(b for b in app.button if b.label == "Executar triagem").click().run()
        assert not app.exception
        doc = app.session_state.resultado_triagem
        assert doc and doc["documento_id"] == doc_id
        assert doc["tipo_arquivo"] == "JSON"
        assert not doc.get("erro_extracao")
        assert doc["armazenamento_oci"]["bucket"] == "mediflow-testes"
        assert doc["armazenamento_oci"]["status_backup"] == "sucesso"
        assert app.session_state.secao_triagem == "resultado"
        for secao in ("classificacao", "extracao", "recebimento", "resultado"):
            app.button(key="secao_triagem_" + secao).click().run()
            assert not app.exception
        # Nova sessão com o mesmo ID: a interface precisa apresentar o 409.
        outro = AppTest.from_file(Path(__file__).resolve().parents[1] / "presentation/web/app.py", default_timeout=180).run()
        outro.switch_page("app_pages/nova_triagem.py").run()
        outro.text_input(key="novo_documento_id").set_value(doc_id)
        next(b for b in outro.button if b.label == "Executar triagem").click().run()
        assert not outro.exception
        assert outro.session_state.resultado_triagem is None
        assert any("ID já está cadastrado" in e.value for e in outro.error)
    saida = {"em": datetime.now(timezone.utc).isoformat(), "documento": doc,
             "verificacoes": ["upload_json_bom_interface", "resultado_real",
                               "navegacao_quatro_secoes", "duplicado_409_interface"],
             "limite": "AppTest com seletor de arquivo injetado; QA visual de navegador não realizada."}
    Path("/evidencias/interface-apptest.json").write_text(
        json.dumps(saida, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("Nova triagem -> API -> Gemini -> OCI: OK; duplicidade e quatro seções: OK", doc_id)


if __name__ == "__main__":
    main()
