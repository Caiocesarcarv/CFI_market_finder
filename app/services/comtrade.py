"""Integração com a UN Comtrade (API de dados v1).

Busca, em UMA requisição, as importações anuais de todos os países para um
código HS, com dois parceiros:
  - 0  (Mundo):  total importado pelo país;
  - 76 (Brasil): quanto o país importou do Brasil (base para a Fase 3).

Os registros são gravados em comtrade_flows. Uma nova consulta só é feita
quando o cache tem mais de CACHE_DAYS dias ou quando refresh=True. Se a API
falhar e houver dados anteriores, eles são usados com um aviso.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from app.config import Settings
from app.services import cache
from app.services.http import ExternalServiceError, request_json

SOURCE = "UN Comtrade"
API_URL = "https://comtradeapi.un.org/data/v1/get/C/A/HS"
WORLD, BRAZIL = 0, 76
CACHE_DAYS = 7
MAX_RECORDS = 100_000  # limite por requisição da assinatura gratuita


def default_years(today: date | None = None, span: int = 5) -> list[int]:
    """Últimos `span` anos encerrados (ex.: em 2026 → 2021..2025)."""
    last = (today or date.today()).year - 1
    return list(range(last - span + 1, last + 1))


def _key(hs_code: str, years: list[int]) -> str:
    return f"{hs_code}|{min(years)}-{max(years)}"


def ensure_imports(
    conn: sqlite3.Connection,
    settings: Settings,
    hs_code: str,
    years: list[int],
    refresh: bool = False,
) -> dict:
    """Garante que os dados de importação estejam no banco.

    Retorna metadados: from_cache, fetched_at, records, warnings.
    Lança ExternalServiceError se não houver dados nem for possível buscá-los.
    """
    key = _key(hs_code, years)
    log = cache.get_log(conn, "comtrade", key)
    warnings: list[str] = []

    if log and not refresh and cache.is_fresh(log, timedelta(days=CACHE_DAYS)):
        return {"from_cache": True, "fetched_at": log["fetched_at"], "records": log["records"], "warnings": warnings}

    if not settings.comtrade_configured:
        if log:
            warnings.append("Chave da UN Comtrade não configurada; exibindo dados salvos anteriormente.")
            return {"from_cache": True, "fetched_at": log["fetched_at"], "records": log["records"], "warnings": warnings}
        raise ExternalServiceError(SOURCE, "chave de API não configurada (COMTRADE_API_KEY no .env)", 503)

    try:
        records = _fetch(settings, hs_code, years)
    except ExternalServiceError as exc:
        if log:
            warnings.append(
                f"Não foi possível atualizar ({exc.message}); exibindo dados obtidos em {log['fetched_at']}."
            )
            return {"from_cache": True, "fetched_at": log["fetched_at"], "records": log["records"], "warnings": warnings}
        raise

    if len(records) >= MAX_RECORDS:
        warnings.append("A resposta atingiu o limite de registros da API; alguns dados podem estar faltando.")

    _store(conn, hs_code, years, records)
    with conn:
        cache.save_log(conn, "comtrade", key, len(records), {"years": years})
    log = cache.get_log(conn, "comtrade", key)
    return {"from_cache": False, "fetched_at": log["fetched_at"], "records": len(records), "warnings": warnings}


def _fetch(settings: Settings, hs_code: str, years: list[int]) -> list[dict]:
    params = {
        "cmdCode": hs_code,
        "flowCode": "M",
        "partnerCode": f"{WORLD},{BRAZIL}",
        "period": ",".join(str(y) for y in sorted(years)),
        # Totais (sem detalhamento por regime aduaneiro, modal ou 2º parceiro)
        "partner2Code": "0",
        "customsCode": "C00",
        "motCode": "0",
        "includeDesc": "true",
    }
    body = request_json(
        "GET", API_URL, source=SOURCE, params=params,
        headers={"Ocp-Apim-Subscription-Key": settings.comtrade_api_key}, timeout=90,
    )
    if not isinstance(body, dict):
        raise ExternalServiceError(SOURCE, "resposta em formato inesperado")
    if body.get("error"):
        raise ExternalServiceError(SOURCE, str(body["error"]))
    return body.get("data") or []


def _store(conn: sqlite3.Connection, hs_code: str, years: list[int], records: list[dict]) -> None:
    rows = []
    for r in records:
        try:
            year = int(r.get("refYear") or r.get("period"))
        except (TypeError, ValueError):
            continue
        rows.append((
            hs_code, year, r.get("flowCode") or "M", int(r["reporterCode"]),
            r.get("reporterISO"), r.get("reporterDesc"), int(r["partnerCode"]),
            r.get("primaryValue"), r.get("cifvalue"), r.get("fobvalue"),
            r.get("netWgt"), r.get("qty"), r.get("qtyUnitAbbr"),
        ))
    placeholders = ",".join("?" * len(years))
    with conn:  # substitui os anos consultados de uma vez (tudo ou nada)
        conn.execute(
            f"DELETE FROM comtrade_flows WHERE cmd_code = ? AND year IN ({placeholders})",
            (hs_code, *years),
        )
        conn.executemany(
            """INSERT OR REPLACE INTO comtrade_flows
               (cmd_code, year, flow, reporter_code, reporter_iso, reporter_name, partner_code,
                value_usd, cif_usd, fob_usd, net_weight_kg, qty, qty_unit)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
