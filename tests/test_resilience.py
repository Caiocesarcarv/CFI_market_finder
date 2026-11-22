"""Fase 6: erros de conexão e ausência de dados, de ponta a ponta pela API.

A falha de rede é simulada na camada HTTP real (requests.Session), então
retentativas, mensagens e uso de cache são exercitados como em produção.
"""

import pytest
import requests
from fastapi.testclient import TestClient

from app.main import create_app
from app.services import comexstat, comtrade, groq_client, http
from app.services.http import ExternalServiceError
from tests.conftest import make_settings
from tests.helpers import seed_reference
from tests.test_analysis import fake_fetch

ENDPOINTS = [
    "/api/trade/0901/imports",
    "/api/trade/0901/evolution",
    "/api/brazil/0901/exports",
    "/api/analysis/0901/markets",
    "/api/analysis/0901/markets/USA",
    "/api/ai/0901/markets/USA",
    "/api/ai/0901/report",
    "/api/classify?q=cafe%20verde",
]


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(http.time, "sleep", lambda s: None)


def offline(monkeypatch):
    def fail(*a, **k):
        raise requests.ConnectionError("rede indisponível")
    monkeypatch.setattr(http._session, "request", fail)


@pytest.fixture
def client(tmp_path):
    settings = make_settings(tmp_path, comtrade="k", groq="g")
    with TestClient(create_app(settings)) as c:
        seed_reference(settings.database_path)
        yield c


# ------------------------------------------------------------------ sem internet


def test_offline_without_cache_gives_clear_errors(client, monkeypatch):
    offline(monkeypatch)
    for path in ENDPOINTS:
        r = client.get(path)
        assert r.status_code in (503, 502), (path, r.status_code, r.text)
        detail = r.json()["detail"]
        assert "conexão" in detail or "internet" in detail, (path, detail)
        assert "Erro interno" not in detail


def test_offline_keeps_local_features(client, monkeypatch):
    offline(monkeypatch)
    assert client.get("/api/health").status_code == 200
    assert client.get("/").status_code == 200
    assert client.post("/api/searches", json={"product_name": "Café", "code": "09011110"}).status_code == 201
    assert client.get("/api/ncm/search", params={"q": "café"}).json()["results"]


def test_offline_with_cache_serves_saved_data(client, monkeypatch):
    # 1) com "internet": dados ficam salvos
    monkeypatch.setattr(comtrade, "_fetch", fake_fetch)
    monkeypatch.setattr(comexstat, "request_json", lambda method, url, **k: (
        {"data": {"year": "2026", "monthNumber": "10"}} if url.endswith("updated") else
        {"success": True, "data": {"list": [
            {"coNcm": "09011110", "year": "2025", "country": "Alemanha", "metricFOB": "300", "metricKG": "30"}]}}))
    assert client.get("/api/analysis/0901/markets").status_code == 200
    assert client.get("/api/brazil/0901/exports").status_code == 200

    # 2) sem internet + pedido de atualização: usa os dados salvos, com aviso
    monkeypatch.undo()
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    offline(monkeypatch)
    r = client.get("/api/analysis/0901/markets", params={"refresh": "true"})
    assert r.status_code == 200
    body = r.json()
    assert body["markets"]
    assert any("Não foi possível atualizar" in w for w in body["warnings"])
    r = client.get("/api/brazil/0901/exports", params={"refresh": "true"})
    assert r.status_code == 200 and r.json()["from_cache"] is True


# ------------------------------------------------------------------ chaves e limites


class Resp:
    def __init__(self, status, body):
        self.status_code, self._body, self.headers, self.text = status, body, {}, str(body)

    def json(self):
        return self._body


def test_invalid_comtrade_key(client, monkeypatch):
    monkeypatch.setattr(http._session, "request", lambda *a, **k: Resp(401, {"statusCode": 401}))
    r = client.get("/api/trade/0901/imports")
    assert r.status_code == 502 and "chave de API inválida" in r.json()["detail"]


def test_groq_rate_limit_reaches_user(client, monkeypatch):
    monkeypatch.setattr(comtrade, "_fetch", fake_fetch)
    monkeypatch.setattr(comexstat, "request_json", lambda *a, **k: (_ for _ in ()).throw(
        ExternalServiceError("Comex Stat", "sem conexão", 503)))
    monkeypatch.setattr(groq_client, "request_json", lambda *a, **k: (_ for _ in ()).throw(
        ExternalServiceError("Groq", "limite de requisições atingido", 429)))
    r = client.get("/api/ai/0901/report")
    assert r.status_code == 429 and "aguarde cerca de 1 minuto" in r.json()["detail"]


# ------------------------------------------------------------------ ausência de dados


def test_product_without_trade_data(client, monkeypatch):
    monkeypatch.setattr(comtrade, "_fetch", lambda *a: [])
    monkeypatch.setattr(comexstat, "request_json", lambda method, url, **k: (
        {"data": {"year": "2026", "monthNumber": "10"}} if url.endswith("updated") else {"success": True, "data": {"list": []}}))

    imports = client.get("/api/trade/0901/imports")
    assert imports.status_code == 200 and imports.json()["importers"] == []
    assert any("não tem registros" in w for w in imports.json()["warnings"])

    exports = client.get("/api/brazil/0901/exports")
    assert exports.status_code == 200 and exports.json()["destinations"] == []
    assert any("não registra exportações" in w for w in exports.json()["warnings"])

    for path in ["/api/analysis/0901/markets", "/api/ai/0901/report", "/api/ai/0901/markets/USA"]:
        r = client.get(path)
        assert r.status_code == 404, path
        assert "não tem registros" in r.json()["detail"]


def test_market_without_supplier_detail_still_ranks(client, monkeypatch):
    def fetch(settings, params):
        return fake_fetch(settings, params) if "partnerCode" in params else []
    monkeypatch.setattr(comtrade, "_fetch", fetch)
    monkeypatch.setattr(comexstat, "request_json", lambda *a, **k: (_ for _ in ()).throw(
        ExternalServiceError("Comex Stat", "sem conexão", 503)))
    body = client.get("/api/analysis/0901/markets").json()
    assert body["markets"]
    assert all(m["indicators"]["hhi"] is None or m["iso3"] == "DEU" for m in body["markets"])


def test_no_endpoint_returns_500_on_bad_input(client):
    for path in ["/api/trade/abc/imports", "/api/analysis/12345/markets", "/api/brazil/99/exports",
                 "/api/ai/0901/markets/XX", "/api/analysis/0901/markets?year=1800", "/api/searches/999999"]:
        r = client.get(path)
        assert 400 <= r.status_code < 500, (path, r.status_code)
