"""Fase 4: análises com IA (Groq simulado; dados FICTÍCIOS de tests/test_analysis.py)."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services import comexstat, comtrade, groq_client
from app.services.ai_insights import pct, usd, verify_numbers
from app.services.http import ExternalServiceError
from tests.conftest import make_settings
from tests.helpers import seed_reference
from tests.test_analysis import fake_fetch

# ------------------------------------------------------------------ formatação e checagem


def test_formatting():
    assert usd(1_760_000_000) == "US$ 1,8 bi"
    assert usd(230_400_000) == "US$ 230,4 mi"
    assert usd(12_400) == "US$ 12 mil"
    assert usd(None) == "n/d"
    assert pct(33.51) == "33,5%" and pct(-3.04, signed=True) == "-3,0%"


def test_market_line_describes_jump_instead_of_huge_rate():
    from app.services.ai_insights import _market_line

    m = {"iso3": "PAK", "country": "Pakistan", "country_pt": "Paquistão", "score": 77.3, "indicators": {
        "imports_usd": 595_500_000, "world_share_pct": 0.74, "cagr_pct": 14490.9, "cagr_period": "2021–2024",
        "cagr_base_value_usd": 192.0, "brazil_share_pct": 0.0, "brazil_supplier_rank": None,
        "leader_supplier": {"iso3": "UKR", "country": "Ucrânia", "share_pct": 40.0}, "brazil_exports_fob_usd": None}}
    line = _market_line(m)
    assert "14490" not in line
    assert "saltaram de US$ 192 (2021) para US$ 595,5 mi" in line
    assert "Brasil não fornece" in line

    m["indicators"].update(cagr_pct=12.0, brazil_share_pct=10.5, brazil_supplier_rank=3)
    line = _market_line(m)
    assert "crescimento 12,0% a.a." in line
    assert "Brasil fornece 10,5% das importações do país, 3º fornecedor" in line


def test_verify_numbers_accepts_data_and_rounding():
    context = "Importações US$ 230,4 mi; Brasil 10,5% do mercado; mundo US$ 31,5 bi; diferença 23,0 pontos percentuais."
    ok = verify_numbers(["O mercado importou US$ 230 milhões e o Brasil tem 10,5%; gap de 23 p.p.",
                         "Mundo: US$ 31,5 bilhões."], context)
    assert ok["ok"] and ok["numbers_checked"] == 4


def test_verify_numbers_flags_invented_values():
    context = "Importações US$ 230,4 mi; Brasil 10,5% do mercado."
    bad = verify_numbers(["O mercado deve chegar a US$ 500 mi, com o Brasil alcançando 25%."], context)
    assert not bad["ok"]
    assert bad["unverified"] == ["US$ 500 mi", "25%"]


# ------------------------------------------------------------------ API


COUNTRY_ANSWER = {
    "resumo": "Os Estados Unidos importaram US$ 1,2 mil e crescem; o Brasil tem 10,0% do mercado.",
    "oportunidades": ["Crescimento de 10,0% ao ano.", ""],
    "riscos": ["Mercado pode cair 40% no ano que vem."],          # número inventado
    "concorrencia": "Colômbia lidera.",
    "estrategia_entrada": ["Buscar compradores que já importam do Brasil."],
    "recomendacoes": [
        {"acao": "Ampliar contratos", "prioridade": "ALTA", "justificativa": "Brasil 10,0%."},
        {"acao": "Prospecção", "prioridade": "urgente", "justificativa": "x"},   # prioridade inválida
        {"acao": "", "prioridade": "alta"},                                       # descartada
    ],
    "pontos_a_verificar": ["Tarifas de importação."],
}

REPORT_ANSWER = {
    "titulo": "Relatório",
    "sumario_executivo": "Mercado mundial relevante.",
    "panorama_mundial": "Colômbia lidera.",
    "mercados_prioritarios": [
        {"iso3": "USA", "justificativa": "Maior mercado.", "estrategia": "Contratos."},
        {"iso3": "FRA", "justificativa": "Inventado.", "estrategia": "-"},   # fora da lista
        {"iso3": "usa", "justificativa": "Duplicado.", "estrategia": "-"},
    ],
    "recomendacoes": [{"acao": "Prospectar", "prioridade": "media", "prazo": "curto", "justificativa": "y"}],
    "riscos_e_limitacoes": ["Dados incompletos."],
    "proximos_passos": ["Verificar tarifas."],
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    calls = []

    def fake_chat(settings, system, user, **kw):
        calls.append({"system": system, "user": user})
        return REPORT_ANSWER if "RELATÓRIO EXECUTIVO" in system else COUNTRY_ANSWER

    monkeypatch.setattr(comtrade, "_fetch", fake_fetch)
    monkeypatch.setattr(comexstat, "request_json", lambda *a, **k: (_ for _ in ()).throw(
        ExternalServiceError("Comex Stat", "sem conexão", 503)))
    monkeypatch.setattr(groq_client, "chat_json", fake_chat)
    settings = make_settings(tmp_path, comtrade="k", groq="g")
    with TestClient(create_app(settings)) as c:
        seed_reference(settings.database_path)
        c.calls = calls
        yield c


def test_country_analysis(client):
    r = client.get("/api/ai/0901/markets/USA", params={"product": "Café"})
    assert r.status_code == 200
    body = r.json()
    assert body["data_nature"] == "estimativa" and body["from_cache"] is False
    assert body["market"]["iso3"] == "USA"

    # a ficha enviada à IA traz dados, guia de leitura e percentis sem "%"
    ficha = client.calls[0]["user"]
    assert "FICHA DE DADOS" in ficha and "GUIA DE LEITURA" in ficha
    assert "de 100" in ficha and "Produto: Café" in ficha
    assert "NUNCA cite nomes próprios" in client.calls[0]["system"]

    c = body["content"]
    assert c["oportunidades"] == ["Crescimento de 10,0% ao ano."]   # item vazio removido
    assert [x["prioridade"] for x in c["recomendacoes"]] == ["alta", "media"]
    assert "40%" in body["verification"]["unverified"]
    assert body["verification"]["ok"] is False
    assert "Atenção" in body["markdown"] and "40%" in body["markdown"]

    # cache: segunda chamada não aciona a IA
    again = client.get("/api/ai/0901/markets/USA", params={"product": "Café"}).json()
    assert again["from_cache"] is True and len(client.calls) == 1
    # refresh força nova geração
    client.get("/api/ai/0901/markets/USA", params={"product": "Café", "refresh": "true"})
    assert len(client.calls) == 2


def test_country_analysis_markdown_download(client):
    r = client.get("/api/ai/0901/markets/USA", params={"format": "md"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert 'filename="analise_0901_USA.md"' in r.headers["content-disposition"]
    assert r.text.startswith("# Estados Unidos")


def test_executive_report(client):
    r = client.get("/api/ai/0901/report", params={"top": 3})
    assert r.status_code == 200
    body = r.json()
    prios = body["content"]["mercados_prioritarios"]
    assert [p["iso3"] for p in prios] == ["USA"]          # FRA descartado, duplicata removida
    assert body["verification"]["rejected_markets"] == ["FRA"]
    assert body["content"]["recomendacoes"][0]["prazo"] == "curto"
    assert len(body["markets_table"]) == 3
    md = body["markdown"]
    assert "## Ranking de mercados (dados da plataforma)" in md
    assert "| 1 |" in md and "Metodologia e fontes" in md
    assert "RELATÓRIO EXECUTIVO" in client.calls[0]["system"]
    assert "MERCADOS AVALIADOS" in client.calls[0]["user"]


def test_ai_without_groq_key(tmp_path, monkeypatch):
    monkeypatch.setattr(comtrade, "_fetch", fake_fetch)
    monkeypatch.setattr(comexstat, "request_json", lambda *a, **k: (_ for _ in ()).throw(
        ExternalServiceError("Comex Stat", "x", 503)))
    with TestClient(create_app(make_settings(tmp_path, comtrade="k", groq=None))) as c:
        r = c.get("/api/ai/0901/report")
    assert r.status_code == 503 and "GROQ_API_KEY" in r.json()["detail"]


def test_groq_rate_limit_message(monkeypatch, tmp_path):
    def limited(*a, **k):
        raise ExternalServiceError("Groq", "limite de requisições atingido", 429)

    monkeypatch.setattr(groq_client, "request_json", limited)
    with pytest.raises(ExternalServiceError) as e:
        groq_client.chat_json(make_settings(tmp_path, groq="g"), "s", "u")
    assert e.value.status_code == 429 and "por minuto" in e.value.message


def test_groq_truncated_answer(monkeypatch, tmp_path):
    monkeypatch.setattr(groq_client, "request_json", lambda *a, **k: {
        "choices": [{"finish_reason": "length", "message": {"content": '{"resumo": "abc'}}]})
    with pytest.raises(ExternalServiceError) as e:
        groq_client.chat_json(make_settings(tmp_path, groq="g"), "s", "u")
    assert "interrompida" in e.value.message


def test_unknown_market_returns_404(client):
    assert client.get("/api/ai/0901/markets/XXX").status_code == 404
    assert client.calls == []  # IA não é chamada sem dados


def test_empty_ai_answer_is_error(client, monkeypatch):
    monkeypatch.setattr(groq_client, "chat_json", lambda *a, **k: {"resumo": ""})
    r = client.get("/api/ai/0901/markets/DEU")
    assert r.status_code == 502 and "vazia" in r.json()["detail"]

