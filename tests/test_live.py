"""Testes com as APIs REAIS (UN Comtrade, Comex Stat, Groq).

Desligados por padrão para não depender de internet nem gastar cota.
Para executar (usa as chaves do .env e um banco temporário):

    set CFI_LIVE_TESTS=1
    venv\\Scripts\\python -m pytest -m live -v

Custo aproximado: 2 consultas à UN Comtrade e 2 chamadas ao Groq (~6 mil tokens).
"""

import os
import time
from dataclasses import replace

import pytest

from app.config import load_settings
from app.database import connect, init_db
from app.services import ai_insights, comtrade, markets, ncm_ai, reference
from app.services.classification import classify_code
from app.services.comexstat import ensure_exports, load_exports
from app.services.http import ExternalServiceError

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.getenv("CFI_LIVE_TESTS") != "1", reason="defina CFI_LIVE_TESTS=1 para usar as APIs reais"),
]

CODE = "09011110"  # café não torrado, em grão


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    settings = replace(load_settings(), database_path=tmp_path_factory.mktemp("live") / "live.db",
                       auto_sync_reference=False)
    if not settings.comtrade_configured:
        pytest.skip("COMTRADE_API_KEY não configurada no .env")
    init_db(settings.database_path)
    conn = connect(settings.database_path)
    reference.sync_ncm(conn)  # a tabela de países (~2 min) é dispensável aqui
    yield settings, conn
    conn.close()


def _groq(fn):
    """Respeita o limite de tokens por minuto do plano gratuito: aguarda e tenta de novo."""
    try:
        return fn()
    except ExternalServiceError as exc:
        if exc.status_code != 429:
            raise
        time.sleep(65)
        return fn()


def test_live_reference_table(env):
    _, conn = env
    assert conn.execute("SELECT COUNT(*) FROM ncm").fetchone()[0] > 10_000
    assert reference.get_ncm(conn, CODE)["description"].startswith("Café não torrado")


def test_live_comtrade(env):
    settings, conn = env
    years = comtrade.default_years()
    meta = comtrade.ensure_imports(conn, settings, "090111", years)
    assert meta["records"] > 100
    usa = conn.execute(
        "SELECT value_usd FROM comtrade_flows WHERE cmd_code='090111' AND reporter_iso='USA' AND partner_code=0 "
        "AND year=?", (years[-2],)).fetchone()
    assert usa and usa[0] > 1e9  # EUA importam bilhões de dólares em café verde


def test_live_comexstat(env):
    _, conn = env
    code = classify_code(CODE)
    meta = ensure_exports(conn, code)
    df = load_exports(conn, code)
    assert meta["latest_year"] >= 2025 and not df.empty
    assert df[df["year"] == meta["latest_year"] - 1]["fob_usd"].sum() > 1e9


def test_live_ranking(env):
    settings, conn = env
    ranking = markets.build_ranking(conn, settings, CODE, top=250)
    assert ranking["benchmark"]["markets_evaluated"] >= 30
    assert ranking["global_suppliers"]["top"][0]["partner_code"] == 76  # Brasil é o maior exportador
    assert all(0 <= m["score"] <= 100 for m in ranking["markets"])


@pytest.mark.skipif(not load_settings().groq_configured, reason="GROQ_API_KEY não configurada")
def test_live_groq_classify(env):
    settings, conn = env
    result = _groq(lambda: ncm_ai.suggest_codes(conn, settings, "café verde em grão", refresh=True))
    codes = [s["ncm"] for s in result["suggestions"]]
    assert CODE in codes, codes
    assert all(reference.get_ncm(conn, c) for c in codes)  # só códigos oficiais


@pytest.mark.skipif(not load_settings().groq_configured, reason="GROQ_API_KEY não configurada")
def test_live_groq_country_analysis(env):
    settings, conn = env
    top = markets.build_ranking(conn, settings, CODE, top=1)["markets"][0]["iso3"]
    result = _groq(lambda: ai_insights.country_analysis(conn, settings, CODE, top, "Café verde", refresh=True))
    assert result["content"]["resumo"]
    assert result["verification"]["numbers_checked"] > 0
    # a IA deve citar apenas números presentes nos dados
    assert result["verification"]["ok"], result["verification"]
