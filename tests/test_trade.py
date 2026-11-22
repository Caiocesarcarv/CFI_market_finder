"""Comtrade + evolução histórica + Comex Stat (APIs externas simuladas)."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services import comexstat, comtrade
from app.services.http import ExternalServiceError
from tests.conftest import make_settings
from tests.helpers import comtrade_record as rec
from tests.helpers import seed_reference

YEARS = comtrade.default_years()  # 5 anos
Y = YEARS[-1]  # último ano


def fake_records():
    rows = []
    # 4 anos "completos" com 3 importadores; último ano só com 2 (incompleto)
    for i, y in enumerate(YEARS):
        rows += [
            rec(y, 840, "USA", "USA", 0, 100.0 + i * 10),
            rec(y, 276, "DEU", "Germany", 0, 80.0 + i * 10),
            rec(y, 276, "DEU", "Germany", 76, 40.0),
            rec(y, 76, "BRA", "Brazil", 0, 5.0),
        ]
        if y != Y:
            rows.append(rec(y, 392, "JPN", "Japan", 0, 50.0))
    return rows


@pytest.fixture
def app_client(tmp_path):
    def build(comtrade_key="k"):
        settings = make_settings(tmp_path, comtrade=comtrade_key)
        app = create_app(settings)
        return TestClient(app), settings
    return build


def test_imports_ranking_and_cache(app_client, monkeypatch):
    calls = []
    monkeypatch.setattr(comtrade, "_fetch", lambda s, p: calls.append(p["cmdCode"]) or fake_records())
    client, _ = app_client()
    with client:
        r = client.get("/api/trade/0901.11.10/imports")
        body = r.json()
        assert r.status_code == 200
        assert body["data_nature"] == "real" and body["hs_code"] == "090111"
        assert calls == ["090111"]
        # último ano incompleto (3 de 4 informantes) → ranking usa o ano anterior
        assert body["year"] == Y - 1
        assert [c["complete"] for c in body["coverage"]][-1] is False
        importers = body["importers"]
        assert [i["iso3"] for i in importers] == ["USA", "DEU", "JPN"]  # Brasil excluído
        assert importers[1]["imports_from_brazil_usd"] == 40.0
        assert importers[0]["yoy_pct"] == pytest.approx((130 / 120 - 1) * 100, abs=0.01)
        assert any("HS6" in w for w in body["warnings"])

        # segunda chamada vem do cache
        assert client.get("/api/trade/090111/imports").json()["from_cache"] is True
        assert calls == ["090111"]

        # ano incompleto pedido explicitamente gera aviso
        r = client.get(f"/api/trade/090111/imports?year={Y}")
        assert any("incompleto" in w for w in r.json()["warnings"])


def test_evolution_like_for_like(app_client, monkeypatch):
    monkeypatch.setattr(comtrade, "_fetch", lambda s, p: fake_records())
    client, _ = app_client()
    with client:
        body = client.get("/api/trade/090111/evolution?iso3=USA").json()
    last = body["world"][-1]
    # Japão ausente no último ano: a variação comparável ignora o Japão
    assert last["comparable_reporters"] == 3
    assert last["yoy_comparable_pct"] == pytest.approx(((140 + 120 + 5) / (130 + 110 + 5) - 1) * 100, abs=0.01)
    assert [c["iso3"] for c in body["countries"]] == ["USA"]
    assert len(body["countries"][0]["values"]) == len(YEARS)


def test_comtrade_failure_without_cache_returns_error(app_client, monkeypatch):
    def boom(*a):
        raise ExternalServiceError("UN Comtrade", "sem conexão com o servidor", 503)
    monkeypatch.setattr(comtrade, "_fetch", boom)
    client, _ = app_client()
    with client:
        r = client.get("/api/trade/090111/imports")
    assert r.status_code == 503
    assert "UN Comtrade" in r.json()["detail"]


def test_comtrade_failure_with_cache_uses_saved_data(app_client, monkeypatch):
    monkeypatch.setattr(comtrade, "_fetch", lambda s, p: fake_records())
    client, _ = app_client()
    with client:
        client.get("/api/trade/090111/imports")

        def boom(*a):
            raise ExternalServiceError("UN Comtrade", "limite de requisições atingido", 429)
        monkeypatch.setattr(comtrade, "_fetch", boom)
        r = client.get("/api/trade/090111/imports?refresh=true")
    assert r.status_code == 200
    assert r.json()["from_cache"] is True
    assert any("Não foi possível atualizar" in w for w in r.json()["warnings"])


def test_comtrade_without_key(app_client):
    client, _ = app_client(comtrade_key=None)
    with client:
        r = client.get("/api/trade/090111/imports")
    assert r.status_code == 503
    assert "COMTRADE_API_KEY" in r.json()["detail"]


def test_comtrade_empty_result(app_client, monkeypatch):
    monkeypatch.setattr(comtrade, "_fetch", lambda *a: [])
    client, _ = app_client()
    with client:
        body = client.get("/api/trade/0901/imports").json()
    assert body["importers"] == []
    assert any("não tem registros" in w for w in body["warnings"])


# ------------------------------------------------------------------ Comex Stat

def fake_comexstat(method, url, **kw):
    if url.endswith("/general/dates/updated"):
        return {"data": {"year": "2026", "monthNumber": "10", "updated": "2026-11-06"}}
    assert kw["json"]["filters"] == [{"filter": "ncm", "values": ["09011110"]}]
    return {"success": True, "data": {"list": [
        {"coNcm": "09011110", "year": "2025", "country": "Alemanha", "metricFOB": "300", "metricKG": "30"},
        {"coNcm": "09011110", "year": "2025", "country": "Estados Unidos", "metricFOB": "200", "metricKG": "20"},
        {"coNcm": "09011110", "year": "2026", "country": "Alemanha", "metricFOB": "100", "metricKG": "10"},
        {"coNcm": "09011110", "year": "2025", "country": "País Desconhecido", "metricFOB": "50", "metricKG": "5"},
    ]}}


def test_brazil_exports(app_client, monkeypatch):
    monkeypatch.setattr(comexstat, "request_json", fake_comexstat)
    client, settings = app_client()
    with client:
        seed_reference(settings.database_path)
        body = client.get("/api/brazil/09011110/exports").json()
    assert body["data_nature"] == "real" and body["reference_year"] == 2025
    assert [d["iso3"] for d in body["destinations"]] == ["DEU", "USA", None]
    assert body["destinations"][0]["share_pct"] == pytest.approx(300 / 550 * 100, abs=0.01)
    partial = [y for y in body["yearly"] if y["partial"]]
    assert [y["year"] for y in partial] == [2026]
    assert any("parcial" in w for w in body["warnings"])
    assert any("País Desconhecido" in w for w in body["warnings"])


def test_import_csv(tmp_path, monkeypatch):
    from app.database import connect, init_db

    db = tmp_path / "x.db"
    init_db(db)
    seed_reference(db)
    csv = tmp_path / "EXP_2024.csv"
    csv.write_text(
        "CO_ANO;CO_MES;CO_NCM;CO_UNID;CO_PAIS;SG_UF_NCM;CO_VIA;CO_URF;QT_ESTAT;KG_LIQUIDO;VL_FOB\n"
        "2024;1;09011110;10;023;MG;1;1;1;100;1000\n"
        "2024;2;09011110;10;023;SP;1;1;1;50;500\n"
        "2024;2;9011110;10;249;SP;1;1;1;10;100\n"     # NCM sem zero à esquerda
        "2024;3;12019000;10;249;PR;1;1;1;999;9999\n",
        encoding="latin-1",
    )
    conn = connect(db)
    result = comexstat.import_csv(conn, csv, ncm_prefix="0901", chunksize=2)
    assert result["years"] == [2024] and result["stored_rows"] == 2
    rows = {r["iso3"]: r["fob_usd"] for r in conn.execute("SELECT * FROM comexstat_exports")}
    assert rows == {"DEU": 1500.0, "USA": 100.0}
    conn.close()


def test_import_csv_rejects_wrong_file(tmp_path):
    from app.database import connect, init_db

    db = tmp_path / "x.db"
    init_db(db)
    bad = tmp_path / "outro.csv"
    bad.write_text("a;b\n1;2\n")
    conn = connect(db)
    with pytest.raises(ValueError):
        comexstat.import_csv(conn, bad)
    conn.close()
