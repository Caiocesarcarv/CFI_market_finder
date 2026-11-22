"""Motor de análise (Fase 3) com dados FICTÍCIOS controlados."""

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services import analysis, comexstat, comtrade, evolution
from app.services.http import ExternalServiceError
from tests.conftest import make_settings
from tests.helpers import comtrade_record as rec
from tests.helpers import seed_reference

YEARS = comtrade.default_years()
REF = YEARS[-2]  # último ano completo no cenário (o último ano fica incompleto)


def series_records():
    """Mundo (0) e Brasil (76) como parceiros, para todos os anos."""
    rows = []
    for i, y in enumerate(YEARS):
        rows += [
            rec(y, 842, "USA", "USA", 0, 1000.0 * (1.1 ** i)),     # grande, +10% a.a.
            rec(y, 842, "USA", "USA", 76, 100.0 * (1.1 ** i)),     # Brasil 10%
            rec(y, 276, "DEU", "Germany", 0, 500.0),               # médio, estável
            rec(y, 276, "DEU", "Germany", 76, 400.0),              # Brasil 80%
            rec(y, 76, "BRA", "Brazil", 0, 50.0),                  # Brasil importador: excluído
            rec(y, 4, "AFG", "Afghanistan", 0, 0.5),               # minúsculo: filtrado
        ]
        if y != YEARS[-1]:  # Japão e China não informam o último ano → ano incompleto
            rows += [
                rec(y, 392, "JPN", "Japan", 0, 300.0),             # Brasil ausente
                rec(y, 156, "CHN", "China", 0, 2.0 if y < REF else 200.0),  # salto
            ]
    return rows


def partner_records():
    """Fornecedores no ano de referência (todos os parceiros)."""
    p = lambda rep, iso, name, pc, piso, pname, v: {
        **rec(REF, rep, iso, name, pc, v), "partnerISO": piso, "partnerDesc": pname}
    usa = 1000.0 * 1.1 ** (len(YEARS) - 2)
    return [
        p(842, "USA", "USA", 76, "BRA", "Brazil", usa * 0.1),
        p(842, "USA", "USA", 170, "COL", "Colombia", usa * 0.9),
        p(276, "DEU", "Germany", 76, "BRA", "Brazil", 400.0),
        p(276, "DEU", "Germany", 704, "VNM", "Viet Nam", 100.0),
        p(392, "JPN", "Japan", 704, "VNM", "Viet Nam", 300.0),
        p(392, "JPN", "Japan", 899, "_X", "Areas, nes", 10.0),   # não-país: ignorado
        # China sem detalhe de fornecedores
    ]


def fake_fetch(settings, params):
    return series_records() if "partnerCode" in params else partner_records()


# ------------------------------------------------------------------ unidade

def test_cagr():
    values = {2021: 100.0, 2022: 110.0, 2023: 121.0, 2024: 133.1}
    growth, base = analysis.cagr(values, 2024, [2021, 2022, 2023, 2024])
    assert base == 2021 and growth == pytest.approx(10.0)
    assert analysis.cagr({2024: 10.0}, 2024, [2024]) == (None, None)


def test_percentile_bounds():
    s = analysis._percentile(pd.Series([1.0, 5.0, None, 3.0]))
    assert s.iloc[0] == 0 and s.iloc[1] == 100 and pd.isna(s.iloc[2]) and s.iloc[3] == pytest.approx(50)


def _rank(conn_rows=None, min_share=analysis.DEFAULT_MIN_SHARE_PCT):
    flows = pd.DataFrame([{
        "year": r["refYear"], "reporter_code": r["reporterCode"], "reporter_iso": r["reporterISO"],
        "reporter_name": r["reporterDesc"], "partner_code": r["partnerCode"], "value_usd": r["primaryValue"],
        "net_weight_kg": r["netWgt"], "qty": r["qty"], "qty_unit": "kg"} for r in series_records()])
    partners = pd.DataFrame([{
        "reporter_code": r["reporterCode"], "reporter_iso": r["reporterISO"], "reporter_name": r["reporterDesc"],
        "partner_code": r["partnerCode"], "partner_iso": r["partnerISO"], "partner_name": r["partnerDesc"],
        "value_usd": r["primaryValue"]} for r in partner_records()])
    # linhas do Brasil vindas da série histórica (como no banco real)
    br = flows[(flows["partner_code"] == 76) & (flows["year"] == REF)]
    partners = pd.concat([partners[partners["partner_code"] != 76], br.assign(
        partner_iso="BRA", partner_name="Brazil")[partners.columns]])
    series = evolution.world_series(flows, YEARS)
    return analysis.rank_markets(flows, partners, series, REF, {"USA": 99.0}, min_share,
                                 {"COL": "Colômbia", "VNM": "Vietnã", "BRA": "Brasil"})


def test_rank_markets_indicators():
    result = _rank()
    markets = {m["iso3"]: m for m in result["markets"]}
    assert set(markets) == {"USA", "DEU", "JPN", "CHN"}  # sem Brasil e sem o minúsculo AFG
    assert result["excluded_small"] == 1

    usa = markets["USA"]["indicators"]
    assert usa["cagr_pct"] == pytest.approx(10.0)
    assert usa["brazil_share_pct"] == pytest.approx(10.0)
    assert usa["hhi"] == pytest.approx(0.1 ** 2 + 0.9 ** 2, abs=1e-3)
    assert usa["leader_supplier"]["country"] == "Colômbia"
    assert usa["brazil_supplier_rank"] == 2
    assert usa["brazil_exports_fob_usd"] == 99.0

    deu = markets["DEU"]["indicators"]
    assert deu["brazil_share_pct"] == pytest.approx(80.0)
    assert deu["brazil_supplier_rank"] == 1
    assert deu["brazil_gap_pp"] < 0  # Brasil acima da sua média mundial
    # HHI total alto (Brasil domina), mas entre concorrentes só há o Vietnã
    assert deu["hhi"] == pytest.approx(0.8 ** 2 + 0.2 ** 2, abs=1e-3)
    assert deu["hhi_competitors"] == pytest.approx(1.0)
    assert usa["hhi_competitors"] == pytest.approx(1.0)  # só a Colômbia além do Brasil

    jpn = markets["JPN"]["indicators"]
    assert jpn["brazil_share_pct"] == 0 and jpn["hhi"] == pytest.approx(1.0)  # "Areas, nes" ignorado

    chn = markets["CHN"]
    assert chn["indicators"]["hhi"] is None  # sem detalhe → indisponível, não 1.0
    assert chn["completeness_pct"] == 85
    assert any("Mercado em formação" in h for h in chn["highlights"])
    assert any("dados parciais" in h for h in chn["highlights"])

    scores = [m["score"] for m in result["markets"]]
    assert scores == sorted(scores, reverse=True)
    assert [m["rank"] for m in result["markets"]] == [1, 2, 3, 4]
    assert all(0 <= s <= 100 for s in scores)


def test_highlights_wording():
    markets = {m["iso3"]: m for m in _rank()["markets"]}
    assert "Brasil ainda não fornece a este mercado" in markets["JPN"]["highlights"]
    assert any(h.startswith("Brasil já é o 1º fornecedor") for h in markets["DEU"]["highlights"])
    assert any("Fornecimento concentrado: Colômbia" in h for h in markets["USA"]["highlights"])
    # Quando quem concentra é o próprio Brasil, não é apresentado como barreira
    assert not any("Fornecimento concentrado" in h for h in markets["DEU"]["highlights"])


def test_global_suppliers():
    partners = pd.DataFrame([{
        "reporter_code": r["reporterCode"], "partner_code": r["partnerCode"], "partner_iso": r["partnerISO"],
        "partner_name": r["partnerDesc"], "value_usd": r["primaryValue"]} for r in partner_records()])
    g = analysis.global_suppliers(partners)
    assert [s["iso3"] for s in g["top"]][0] == "COL"
    assert g["brazil"]["iso3"] == "BRA"
    assert "_X" not in [s["iso3"] for s in g["top"]]


# ------------------------------------------------------------------ API

@pytest.fixture
def client(tmp_path, monkeypatch):
    settings = make_settings(tmp_path, comtrade="k")
    monkeypatch.setattr(comtrade, "_fetch", fake_fetch)
    monkeypatch.setattr(comexstat, "request_json", lambda *a, **k: (_ for _ in ()).throw(
        ExternalServiceError("Comex Stat", "sem conexão com o servidor", 503)))
    with TestClient(create_app(settings)) as c:
        seed_reference(settings.database_path)
        yield c


def test_markets_endpoint(client):
    r = client.get("/api/analysis/0901/markets")
    assert r.status_code == 200
    body = r.json()
    assert body["data_nature"] == "estimativa"
    assert body["reference_year"] == REF
    assert sum(body["methodology"]["weights"].values()) == pytest.approx(1.0)
    assert body["benchmark"]["markets_evaluated"] == 4
    assert body["global_suppliers"]["brazil"]["iso3"] == "BRA"
    # Comex Stat fora do ar não derruba a análise
    assert any("Exportações brasileiras indisponíveis" in w for w in body["warnings"])
    assert body["source"] == "Cálculo CFI sobre UN Comtrade"
    usa = next(m for m in body["markets"] if m["iso3"] == "USA")
    assert usa["country_pt"] == "Estados Unidos"


def test_market_detail_endpoint(client):
    body = client.get("/api/analysis/0901/markets/usa").json()
    assert body["market"]["iso3"] == "USA" and body["in_main_ranking"] is True
    assert [s["iso3"] for s in body["suppliers"]] == ["COL", "BRA"]
    assert len(body["history"]) == len(YEARS)

    small = client.get("/api/analysis/0901/markets/AFG").json()
    assert small["in_main_ranking"] is False
    assert any("fora do ranking principal" in w for w in small["warnings"])

    assert client.get("/api/analysis/0901/markets/XXX").status_code == 404


def test_partner_detail_failure_degrades(tmp_path, monkeypatch):
    def fetch(settings, params):
        if "partnerCode" in params:
            return series_records()
        raise ExternalServiceError("UN Comtrade", "limite de requisições atingido", 429)

    monkeypatch.setattr(comtrade, "_fetch", fetch)
    monkeypatch.setattr(comexstat, "request_json", lambda *a, **k: (_ for _ in ()).throw(
        ExternalServiceError("Comex Stat", "x", 503)))
    with TestClient(create_app(make_settings(tmp_path, comtrade="k"))) as c:
        body = c.get("/api/analysis/0901/markets").json()
    assert any("Detalhe de fornecedores indisponível" in w for w in body["warnings"])
    assert all(m["indicators"]["hhi"] is None for m in body["markets"] if m["iso3"] != "DEU")
    assert all(m["completeness_pct"] < 100 for m in body["markets"])


def test_partner_detail_does_not_erase_series(tmp_path, monkeypatch):
    """A consulta de fornecedores não pode apagar a série histórica (e vice-versa)."""
    from app.database import connect

    monkeypatch.setattr(comtrade, "_fetch", fake_fetch)
    settings = make_settings(tmp_path, comtrade="k")
    with TestClient(create_app(settings)):
        conn = connect(settings.database_path)
        comtrade.ensure_imports(conn, settings, "0901", YEARS)
        before = conn.execute("SELECT COUNT(*) FROM comtrade_flows WHERE partner_code IN (0,76)").fetchone()[0]
        comtrade.ensure_partner_detail(conn, settings, "0901", REF)
        comtrade.ensure_imports(conn, settings, "0901", YEARS, refresh=True)
        after = conn.execute("SELECT COUNT(*) FROM comtrade_flows WHERE partner_code IN (0,76)").fetchone()[0]
        others = conn.execute("SELECT COUNT(*) FROM comtrade_flows WHERE partner_code NOT IN (0,76)").fetchone()[0]
        conn.close()
    assert before == after > 0 and others == 4  # 6 fornecedores, 2 deles o Brasil
