from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_settings


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["database"]["ok"] is True
    assert body["integrations"]["comtrade"]["configured"] is False
    assert body["integrations"]["groq"]["configured"] is False
    assert body["data_natures"] == ["real", "estimativa", "demonstrativo"]


def test_health_never_exposes_keys(tmp_path):
    app = create_app(make_settings(tmp_path, comtrade="SEGREDO-123", groq="SEGREDO-456"))
    with TestClient(app) as c:
        r = c.get("/api/health")
    assert r.json()["integrations"]["comtrade"]["configured"] is True
    assert "SEGREDO" not in r.text


def test_frontend_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "CFI Market Finder" in r.text
    for path in ["/css/styles.css", "/js/theme.js", "/js/ui.js", "/js/api.js", "/js/charts.js", "/js/map.js",
                 "/js/report.js", "/js/dashboard.js", "/js/app.js"]:
        assert client.get(path).status_code == 200, path


def test_favicon(client):
    for path in ["/favicon.ico", "/favicon.svg"]:
        r = client.get(path)
        assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml"), path
    assert 'rel="icon"' in client.get("/").text


def test_vendor_libraries_are_local(client):
    """Plotly, Leaflet e o mapa-múndi são servidos localmente (sem CDN)."""
    html = client.get("/").text
    assert "http://" not in html and "https://" not in html.replace('href="/docs"', "")
    for path in ["/vendor/plotly/plotly-basic.min.js", "/vendor/leaflet/leaflet.js",
                 "/vendor/leaflet/leaflet.css", "/vendor/geo/world-countries.geojson"]:
        r = client.get(path)
        assert r.status_code == 200 and len(r.content) > 1000, path
    geo = client.get("/vendor/geo/world-countries.geojson").json()
    isos = {f["properties"]["iso3"] for f in geo["features"]}
    assert {"BRA", "USA", "CHN", "DEU", "FRA", "MAR"} <= isos


def test_search_crud(client):
    r = client.post("/api/searches", json={"product_name": "Café verde", "code": "0901.11.10"})
    assert r.status_code == 201
    created = r.json()
    assert created["code_type"] == "NCM"
    assert created["hs_code"] == "090111"

    assert client.get(f"/api/searches/{created['id']}").json()["product_name"] == "Café verde"
    assert len(client.get("/api/searches").json()) == 1

    assert client.delete(f"/api/searches/{created['id']}").status_code == 204
    assert client.get(f"/api/searches/{created['id']}").status_code == 404
    assert client.delete(f"/api/searches/{created['id']}").status_code == 404


def test_search_invalid_code(client):
    r = client.post("/api/searches", json={"product_name": "Teste", "code": "12345"})
    assert r.status_code == 422
    assert "dígitos" in r.json()["detail"]


def test_search_invalid_product_name(client):
    r = client.post("/api/searches", json={"product_name": "", "code": "0901"})
    assert r.status_code == 422


def test_validate_code(client):
    assert client.get("/api/searches/validate-code", params={"code": "0901"}).json()["valid"] is True
    bad = client.get("/api/searches/validate-code", params={"code": "99"}).json()
    assert bad["valid"] is False and bad["message"]
