"""Tabela NCM, validação oficial de códigos e sugestão por IA (Groq simulado)."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services import groq_client
from tests.conftest import make_settings
from tests.helpers import seed_reference


@pytest.fixture
def seeded(tmp_path):
    def build(groq="g"):
        settings = make_settings(tmp_path, groq=groq)
        client = TestClient(create_app(settings))
        client.__enter__()
        seed_reference(settings.database_path)
        return client
    clients = []
    yield lambda **kw: clients.append(build(**kw)) or clients[-1]
    for c in clients:
        c.__exit__(None, None, None)


def test_ncm_search_ignores_accents(seeded):
    client = seeded()
    results = client.get("/api/ncm/search", params={"q": "cafe grao"}).json()["results"]
    assert results[0]["co_ncm"] == "09011110"
    assert client.get("/api/ncm/search", params={"q": "0901"}).json()["results"][0]["co_ncm"].startswith("0901")


def test_iso3_names_use_main_country(tmp_path):
    from app.database import connect, init_db
    from app.services.reference import country_index, iso3_names_pt

    db = tmp_path / "x.db"
    init_db(db)
    seed_reference(db)
    conn = connect(db)
    names = iso3_names_pt(conn)
    assert names["DEU"] == "Alemanha" and names["USA"] == "Estados Unidos"
    assert "ZZZ" not in names
    assert country_index(conn)["Não Declarados"]["iso3"] is None
    conn.close()


def test_official_validation_of_codes(seeded):
    client = seeded()
    ok = client.get("/api/searches/validate-code", params={"code": "0901.11.10"}).json()
    assert ok["valid"] and ok["official_description"].startswith("Café")
    bad = client.get("/api/searches/validate-code", params={"code": "0901.11.99"}).json()
    assert bad["valid"] is False and "não existe" in bad["message"]
    r = client.post("/api/searches", json={"product_name": "Teste", "code": "09019999"})
    assert r.status_code == 422


def test_classify_validates_ai_suggestions(seeded, monkeypatch):
    calls = []

    def fake_chat(settings, system, user, temperature=0.1):
        calls.append(user)
        return {
            "interpretacao": "Café verde em grão",
            "sugestoes": [
                {"ncm": "0901.11.10", "confianca": "alta", "justificativa": "Café não torrado em grão."},
                {"ncm": "09011199", "confianca": "media", "justificativa": "Código inventado."},
                {"ncm": "09011190", "confianca": "certeza", "justificativa": "Exceto em grão."},
            ],
            "observacao": "",
        }

    monkeypatch.setattr(groq_client, "chat_json", fake_chat)
    client = seeded()
    body = client.get("/api/classify", params={"q": "café verde em grão"}).json()

    assert body["data_nature"] == "estimativa"
    assert [s["ncm"] for s in body["suggestions"]] == ["09011110", "09011190"]
    assert body["suggestions"][0]["official_description"] == "Café não torrado, não descafeinado, em grão"
    assert body["suggestions"][1]["confidence"] == "baixa"  # valor fora do padrão é rebaixado
    assert body["discarded"][0]["ncm"] == "09011199"
    assert "09011110 - Café" in calls[0]  # candidatos oficiais enviados à IA

    again = client.get("/api/classify", params={"q": "Cafe  VERDE em grao"}).json()
    assert again["from_cache"] is True and len(calls) == 1


def test_classify_without_groq_key(seeded):
    client = seeded(groq=None)
    r = client.get("/api/classify", params={"q": "café"})
    assert r.status_code == 503 and "GROQ_API_KEY" in r.json()["detail"]


def test_classify_before_reference_ready(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, groq="g"))) as client:
        r = client.get("/api/classify", params={"q": "café"})
    assert r.status_code == 503 and "NCM" in r.json()["detail"]
