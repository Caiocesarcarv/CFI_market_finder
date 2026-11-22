"""Integração com a UN Comtrade (API de dados v1).

Duas consultas, ambas gravadas em comtrade_flows:

1. Série histórica (ensure_imports): importações anuais de todos os países
   para um código HS, com os parceiros 0 (Mundo) e 76 (Brasil). Uma
   requisição para todo o período.
2. Fornecedores (ensure_partner_detail): importações de todos os países
   detalhadas por país de origem, para UM ano. Base para "principais
   fornecedores" e concentração de mercado (Fase 3).

Uma nova consulta só é feita quando o cache tem mais de CACHE_DAYS dias ou
quando refresh=True. Se a API falhar e houver dados anteriores, eles são
usados com um aviso.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import date, timedelta

from app.config import Settings
from app.services import cache
from app.services.http import ExternalServiceError, request_json

SOURCE = "UN Comtrade"
API_URL = "https://comtradeapi.un.org/data/v1/get/C/A/HS"
WORLD, BRAZIL = 0, 76
CACHE_DAYS = 7
MAX_RECORDS = 100_000  # limite por requisição da assinatura gratuita

# Parceiros da Comtrade que não são países (excluídos dos rankings de fornecedores)
NON_COUNTRY_PARTNERS = {
    0,    # World
    837,  # Bunkers
    838,  # Free Zones
    839,  # Special Categories
    899,  # Areas, nes
}


def default_years(today: date | None = None, span: int = 5) -> list[int]:
    """Últimos `span` anos encerrados (ex.: em 2026 → 2021..2025)."""
    last = (today or date.today()).year - 1
    return list(range(last - span + 1, last + 1))


# ---------------------------------------------------------------- consultas

def ensure_imports(
    conn: sqlite3.Connection, settings: Settings, hs_code: str, years: list[int], refresh: bool = False
) -> dict:
    """Série histórica (Mundo e Brasil como parceiros) para os anos informados."""
    key = f"{hs_code}|{min(years)}-{max(years)}"
    params = {"cmdCode": hs_code, "partnerCode": f"{WORLD},{BRAZIL}", "period": ",".join(map(str, sorted(years)))}

    def store(records):
        _store(conn, hs_code, records, years, partner_scope="world_brazil")

    return _ensure(conn, settings, "comtrade", key, params, store, refresh, {"years": years})


def ensure_partner_detail(
    conn: sqlite3.Connection, settings: Settings, hs_code: str, year: int, refresh: bool = False
) -> dict:
    """Importações de um ano detalhadas por país fornecedor (todos os parceiros)."""
    key = f"{hs_code}|{year}"
    params = {"cmdCode": hs_code, "period": str(year)}  # sem partnerCode = todos os parceiros

    def store(records):
        _store(conn, hs_code, records, [year], partner_scope="others")

    return _ensure(conn, settings, "comtrade_partners", key, params, store, refresh, {"year": year})


def _ensure(
    conn: sqlite3.Connection,
    settings: Settings,
    source_key: str,
    key: str,
    params: dict,
    store: Callable[[list[dict]], None],
    refresh: bool,
    meta: dict,
) -> dict:
    """Lógica comum de cache → consulta → gravação → fallback."""
    log = cache.get_log(conn, source_key, key)
    warnings: list[str] = []

    def cached(extra: str | None = None) -> dict:
        if extra:
            warnings.append(extra)
        return {"from_cache": True, "fetched_at": log["fetched_at"], "records": log["records"], "warnings": warnings}

    if log and not refresh and cache.is_fresh(log, timedelta(days=CACHE_DAYS)):
        return cached()

    if not settings.comtrade_configured:
        if log:
            return cached("Chave da UN Comtrade não configurada; exibindo dados salvos anteriormente.")
        raise ExternalServiceError(SOURCE, "chave de API não configurada (COMTRADE_API_KEY no .env)", 503)

    try:
        records = _fetch(settings, params)
    except ExternalServiceError as exc:
        if log:
            return cached(f"Não foi possível atualizar ({exc.message}); exibindo dados obtidos em {log['fetched_at']}.")
        raise

    if len(records) >= MAX_RECORDS:
        warnings.append("A resposta atingiu o limite de registros da API; alguns dados podem estar faltando.")

    store(records)
    with conn:
        cache.save_log(conn, source_key, key, len(records), meta)
    log = cache.get_log(conn, source_key, key)
    return {"from_cache": False, "fetched_at": log["fetched_at"], "records": len(records), "warnings": warnings}


def _fetch(settings: Settings, params: dict) -> list[dict]:
    full = {
        "flowCode": "M",
        # Totais (sem detalhamento por regime aduaneiro, modal ou 2º parceiro)
        "partner2Code": "0",
        "customsCode": "C00",
        "motCode": "0",
        "includeDesc": "true",
        **params,
    }
    body = request_json(
        "GET", API_URL, source=SOURCE, params=full,
        headers={"Ocp-Apim-Subscription-Key": settings.comtrade_api_key}, timeout=120,
    )
    if not isinstance(body, dict):
        raise ExternalServiceError(SOURCE, "resposta em formato inesperado")
    if body.get("error"):
        raise ExternalServiceError(SOURCE, str(body["error"]))
    return body.get("data") or []


def _store(conn: sqlite3.Connection, hs_code: str, records: list[dict], years: list[int], partner_scope: str) -> None:
    """Grava os registros substituindo apenas o escopo consultado.

    partner_scope="world_brazil": parceiros 0 e 76 (série histórica);
    partner_scope="others": demais parceiros (detalhe de fornecedores).
    Assim uma consulta nunca apaga os dados da outra.
    """
    core = (WORLD, BRAZIL)
    rows = []
    for r in records:
        try:
            year = int(r.get("refYear") or r.get("period"))
            partner = int(r["partnerCode"])
        except (TypeError, ValueError, KeyError):
            continue
        if (partner in core) != (partner_scope == "world_brazil"):
            continue
        rows.append((
            hs_code, year, r.get("flowCode") or "M", int(r["reporterCode"]),
            r.get("reporterISO"), r.get("reporterDesc"), partner,
            (r.get("partnerISO") or "").strip() or None, r.get("partnerDesc"),
            r.get("primaryValue"), r.get("cifvalue"), r.get("fobvalue"),
            r.get("netWgt"), r.get("qty"), r.get("qtyUnitAbbr"),
        ))
    placeholders = ",".join("?" * len(years))
    scope_sql = "partner_code IN (0, 76)" if partner_scope == "world_brazil" else "partner_code NOT IN (0, 76)"
    with conn:  # substitui o escopo de uma vez (tudo ou nada)
        conn.execute(
            f"DELETE FROM comtrade_flows WHERE cmd_code = ? AND year IN ({placeholders}) AND {scope_sql}",
            (hs_code, *years),
        )
        conn.executemany(
            """INSERT OR REPLACE INTO comtrade_flows
               (cmd_code, year, flow, reporter_code, reporter_iso, reporter_name, partner_code,
                partner_iso, partner_name, value_usd, cif_usd, fob_usd, net_weight_kg, qty, qty_unit)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
