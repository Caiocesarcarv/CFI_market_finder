"""Exportações brasileiras (Comex Stat / MDIC).

Duas formas de carga, gravando na mesma tabela comexstat_exports:

1. API pública (api-comexstat.mdic.gov.br) — automática, por código
   consultado, com cache de CACHE_DAYS dias.
2. Importação de CSV — arquivos oficiais EXP_AAAA.csv (base completa por NCM)
   colocados manualmente; ver app/tools/import_comexstat_csv.py. Útil para
   trabalhar sem internet ou carregar muitos anos de uma vez.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from app.services import cache
from app.services.classification import ClassifiedCode
from app.services.http import ExternalServiceError, request_json
from app.services.reference import COMEXSTAT_API, clean_iso3, country_index

SOURCE = "Comex Stat"
CACHE_DAYS = 7

# Tipo de código → filtro da API do Comex Stat
_FILTERS = {"NCM": "ncm", "HS6": "subHeading", "HS4": "heading", "HS2": "chapter"}


# ---------------------------------------------------------------- API

def latest_available(conn: sqlite3.Connection) -> dict:
    """Último ano/mês publicado no Comex Stat (consulta cacheada por 1 dia)."""
    log = cache.get_log(conn, "comexstat", "dates/updated")
    if log and cache.is_fresh(log, timedelta(days=1)):
        return log["meta"]
    try:
        body = request_json("GET", f"{COMEXSTAT_API}/general/dates/updated", source=SOURCE, timeout=30)
        d = body.get("data") or {}
        meta = {"year": int(d["year"]), "month": int(d["monthNumber"]), "updated": d.get("updated")}
    except (ExternalServiceError, KeyError, TypeError, ValueError):
        if log:
            return log["meta"]
        today = date.today()  # suposição conservadora: mês anterior ao atual
        meta = {"year": today.year if today.month > 1 else today.year - 1,
                "month": today.month - 1 or 12, "updated": None, "assumed": True}
        return meta
    with conn:
        cache.save_log(conn, "comexstat", "dates/updated", 1, meta)
    return meta


def ensure_exports(conn: sqlite3.Connection, code: ClassifiedCode, years_back: int = 5, refresh: bool = False) -> dict:
    """Garante que as exportações do código estejam no banco (anos fechados + ano corrente parcial)."""
    latest = latest_available(conn)
    first_year = latest["year"] - years_back
    key = f"{code.code_digits}|{first_year}-{latest['year']}"
    log = cache.get_log(conn, "comexstat", key)
    warnings: list[str] = []
    meta = {"latest_year": latest["year"], "latest_month": latest["month"], "first_year": first_year}

    if log and not refresh and cache.is_fresh(log, timedelta(days=CACHE_DAYS)):
        return {**meta, "from_cache": True, "fetched_at": log["fetched_at"], "records": log["records"], "warnings": warnings}

    payload = {
        "flow": "export",
        "monthDetail": False,
        "period": {"from": f"{first_year}-01", "to": f"{latest['year']}-{latest['month']:02d}"},
        "filters": [{"filter": _FILTERS[code.code_type], "values": [code.code_digits]}],
        "details": ["country", "ncm"],
        "metrics": ["metricFOB", "metricKG"],
    }
    try:
        body = request_json("POST", f"{COMEXSTAT_API}/general", source=SOURCE,
                            params={"language": "pt"}, json=payload, timeout=120)
        if not body.get("success", True):
            raise ExternalServiceError(SOURCE, body.get("message") or "consulta recusada")
        items = (body.get("data") or {}).get("list") or []
    except ExternalServiceError as exc:
        if _has_rows(conn, code):
            when = log["fetched_at"] if log else "importação anterior"
            warnings.append(f"Não foi possível atualizar ({exc.message}); exibindo dados salvos ({when}).")
            return {**meta, "from_cache": True, "fetched_at": log["fetched_at"] if log else None,
                    "records": None, "warnings": warnings}
        raise

    _store_api_rows(conn, code, items, first_year)
    with conn:
        cache.save_log(conn, "comexstat", key, len(items), meta)
    log = cache.get_log(conn, "comexstat", key)
    return {**meta, "from_cache": False, "fetched_at": log["fetched_at"], "records": len(items), "warnings": warnings}


def _ncm_where(code: ClassifiedCode) -> tuple[str, tuple]:
    if code.code_type == "NCM":
        return "co_ncm = ?", (code.code_digits,)
    return "co_ncm LIKE ?", (code.code_digits + "%",)


def _has_rows(conn: sqlite3.Connection, code: ClassifiedCode) -> bool:
    where, args = _ncm_where(code)
    return conn.execute(f"SELECT EXISTS(SELECT 1 FROM comexstat_exports WHERE {where})", args).fetchone()[0] == 1


def _store_api_rows(conn: sqlite3.Connection, code: ClassifiedCode, items: list[dict], first_year: int) -> None:
    countries = country_index(conn)
    rows = []
    for i in items:
        name = i.get("country") or "Não informado"
        ref = countries.get(name, {})
        rows.append((
            str(i["coNcm"]).zfill(8), int(i["year"]), ref.get("co_pais") or name, name, ref.get("iso3"),
            float(i.get("metricFOB") or 0), float(i.get("metricKG") or 0),
        ))
    where, args = _ncm_where(code)
    with conn:
        conn.execute(f"DELETE FROM comexstat_exports WHERE {where} AND year >= ? AND origin = 'api'",
                     (*args, first_year))
        conn.executemany(
            """INSERT OR REPLACE INTO comexstat_exports
               (co_ncm, year, co_pais, country_name, iso3, fob_usd, net_weight_kg, origin)
               VALUES (?,?,?,?,?,?,?,'api')""",
            rows,
        )


def load_exports(conn: sqlite3.Connection, code: ClassifiedCode) -> pd.DataFrame:
    """Exportações por ano e destino (soma das NCMs do código consultado)."""
    where, args = _ncm_where(code)
    return pd.read_sql_query(
        f"""SELECT year, co_pais, country_name, NULLIF(iso3, 'ZZZ') AS iso3,
                   SUM(fob_usd) AS fob_usd, SUM(net_weight_kg) AS net_weight_kg,
                   GROUP_CONCAT(DISTINCT origin) AS origin
            FROM comexstat_exports WHERE {where}
            GROUP BY year, co_pais, country_name, NULLIF(iso3, 'ZZZ')""",
        conn, params=args,
    )


# ---------------------------------------------------------------- CSV

CSV_COLUMNS = ["CO_ANO", "CO_NCM", "CO_PAIS", "KG_LIQUIDO", "VL_FOB"]


def import_csv(conn: sqlite3.Connection, path: Path, ncm_prefix: str | None = None,
               chunksize: int = 500_000) -> dict:
    """Importa um arquivo oficial EXP_AAAA.csv (separador ';').

    Agrega por ano, NCM e país e grava em comexstat_exports com origin='csv'.
    ncm_prefix opcional restringe a importação (ex.: '09' para o capítulo 9).
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")

    header = pd.read_csv(path, sep=";", nrows=0, encoding="latin-1")
    missing = [c for c in CSV_COLUMNS if c not in header.columns]
    if missing:
        raise ValueError(f"{path.name} não parece um EXP_AAAA.csv do Comex Stat; faltam colunas: {missing}")

    parts = []
    read_rows = 0
    for chunk in pd.read_csv(path, sep=";", usecols=CSV_COLUMNS, dtype={"CO_NCM": str, "CO_PAIS": str},
                             encoding="latin-1", chunksize=chunksize):
        read_rows += len(chunk)
        chunk["CO_NCM"] = chunk["CO_NCM"].str.strip().str.zfill(8)
        if ncm_prefix:
            chunk = chunk[chunk["CO_NCM"].str.startswith(ncm_prefix)]
        parts.append(chunk.groupby(["CO_ANO", "CO_NCM", "CO_PAIS"], as_index=False)[["VL_FOB", "KG_LIQUIDO"]].sum())

    if not parts:
        return {"file": path.name, "read_rows": 0, "stored_rows": 0, "years": []}
    agg = pd.concat(parts).groupby(["CO_ANO", "CO_NCM", "CO_PAIS"], as_index=False)[["VL_FOB", "KG_LIQUIDO"]].sum()
    agg["CO_PAIS"] = agg["CO_PAIS"].str.strip().str.zfill(3)

    by_code = {
        r["co_pais"]: (r["name_pt"], clean_iso3(r["iso3"]))
        for r in conn.execute("SELECT co_pais, name_pt, iso3 FROM countries")
    }
    rows = [
        (r.CO_NCM, int(r.CO_ANO), r.CO_PAIS, *by_code.get(r.CO_PAIS, (None, None)),
         float(r.VL_FOB), float(r.KG_LIQUIDO))
        for r in agg.itertuples(index=False)
    ]
    years = sorted(int(y) for y in agg["CO_ANO"].unique())
    with conn:
        conn.executemany(
            """INSERT OR REPLACE INTO comexstat_exports
               (co_ncm, year, co_pais, country_name, iso3, fob_usd, net_weight_kg, origin)
               VALUES (?,?,?,?,?,?,?,'csv')""",
            rows,
        )
    return {"file": path.name, "read_rows": read_rows, "stored_rows": len(rows), "years": years}
