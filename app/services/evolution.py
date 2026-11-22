"""Evolução histórica das importações (Pandas) a partir de comtrade_flows.

Cuidados de leitura:
- A UN Comtrade recebe os dados de cada país com atraso; os anos mais
  recentes costumam ter menos países informantes. Um ano é marcado como
  "incompleto" quando tem menos de COMPLETE_RATIO do maior número de
  informantes do período.
- A variação mundial é calculada "like-for-like": só entram países com
  dados nos dois anos comparados, para que a falta de informantes não pareça
  queda de mercado.
"""

from __future__ import annotations

import math
import sqlite3

import pandas as pd

from app.services.comtrade import BRAZIL, WORLD

COMPLETE_RATIO = 0.85


def load_flows(conn: sqlite3.Connection, hs_code: str, years: list[int]) -> pd.DataFrame:
    placeholders = ",".join("?" * len(years))
    return pd.read_sql_query(
        f"""SELECT year, reporter_code, reporter_iso, reporter_name, partner_code,
                   value_usd, net_weight_kg, qty, qty_unit
            FROM comtrade_flows
            WHERE cmd_code = ? AND flow = 'M' AND year IN ({placeholders})""",
        conn, params=(hs_code, *years),
    )


def _num(value) -> float | None:
    """Converte para float serializável (NaN → None)."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def _pct(new, old) -> float | None:
    new, old = _num(new), _num(old)
    if new is None or not old:
        return None
    return round((new / old - 1) * 100, 2)


def world_series(df: pd.DataFrame, years: list[int]) -> list[dict]:
    """Total importado pelo mundo por ano, cobertura e variação comparável."""
    world = df[df["partner_code"] == WORLD]
    max_reporters = int(world.groupby("year")["reporter_code"].nunique().max()) if not world.empty else 0
    out = []
    prev_year_set = None
    for year in sorted(years):
        ydf = world[world["year"] == year]
        reporters = set(ydf["reporter_code"])
        item = {
            "year": year,
            "total_usd": _num(ydf["value_usd"].sum()) if not ydf.empty else None,
            "reporters": len(reporters),
            "complete": bool(max_reporters and len(reporters) >= COMPLETE_RATIO * max_reporters),
            "yoy_comparable_pct": None,
            "comparable_reporters": None,
        }
        if prev_year_set is not None and reporters:
            common = reporters & prev_year_set
            prev_df = world[(world["year"] == year - 1) & world["reporter_code"].isin(common)]
            cur_df = ydf[ydf["reporter_code"].isin(common)]
            item["yoy_comparable_pct"] = _pct(cur_df["value_usd"].sum(), prev_df["value_usd"].sum())
            item["comparable_reporters"] = len(common)
        prev_year_set = reporters
        out.append(item)
    return out


def latest_complete_year(series: list[dict]) -> int | None:
    complete = [s["year"] for s in series if s["complete"]]
    return max(complete) if complete else None


def importers_ranking(df: pd.DataFrame, year: int, exclude_brazil: bool = True) -> list[dict]:
    """Países importadores no ano, do maior para o menor, com variação anual.

    O Brasil é excluído por padrão, pois o objetivo é achar mercados de destino.
    """
    world = df[df["partner_code"] == WORLD]
    from_br = df[df["partner_code"] == BRAZIL].set_index(["reporter_code", "year"])["value_usd"]
    cur = world[world["year"] == year]
    prev = world[world["year"] == year - 1].set_index("reporter_code")["value_usd"]
    if exclude_brazil:
        cur = cur[cur["reporter_code"] != BRAZIL]
    total = cur["value_usd"].sum()

    rows = []
    for r in cur.sort_values("value_usd", ascending=False).itertuples(index=False):
        rows.append({
            "reporter_code": int(r.reporter_code),
            "iso3": r.reporter_iso,
            "country": r.reporter_name,
            "value_usd": _num(r.value_usd),
            "net_weight_kg": _num(r.net_weight_kg),
            "world_share_pct": round(float(r.value_usd / total * 100), 2) if total else None,
            "previous_value_usd": _num(prev.get(r.reporter_code)),
            "yoy_pct": _pct(r.value_usd, prev.get(r.reporter_code)),
            # Valor importado do Brasil segundo o próprio importador (None = não informado)
            "imports_from_brazil_usd": _num(from_br.get((r.reporter_code, year))),
        })
    return rows


def country_series(df: pd.DataFrame, years: list[int], iso3: list[str] | None = None, top: int = 10) -> list[dict]:
    """Série anual por país. Sem iso3, usa os `top` maiores importadores do último ano com dados."""
    world = df[(df["partner_code"] == WORLD) & (df["reporter_code"] != BRAZIL)]
    if world.empty:
        return []
    if iso3:
        wanted = {c.upper() for c in iso3}
        chosen = world[world["reporter_iso"].isin(wanted)]["reporter_code"].unique()
    else:
        last = world["year"].max()
        chosen = world[world["year"] == last].nlargest(top, "value_usd")["reporter_code"].tolist()

    out = []
    for code in chosen:
        cdf = world[world["reporter_code"] == code].set_index("year")
        first = cdf.iloc[0]
        values = [{"year": y, "value_usd": _num(cdf["value_usd"].get(y))} for y in sorted(years)]
        for i in range(1, len(values)):
            values[i]["yoy_pct"] = _pct(values[i]["value_usd"], values[i - 1]["value_usd"])
        values[0]["yoy_pct"] = None
        out.append({
            "reporter_code": int(code),
            "iso3": first["reporter_iso"],
            "country": first["reporter_name"],
            "values": values,
            "years_with_data": int(cdf["value_usd"].notna().sum()),
        })
    return out
