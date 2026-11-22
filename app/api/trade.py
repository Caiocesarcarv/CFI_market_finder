"""Dados comerciais reais: importações mundiais (UN Comtrade) e
exportações brasileiras (Comex Stat)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from app.api.deps import get_db, get_settings
from app.config import Settings
from app.models import DataNature
from app.services import comexstat, comtrade, evolution
from app.services.classification import ClassifiedCode, InvalidCodeError, classify_code
from app.services.reference import iso3_names_pt

router = APIRouter(tags=["dados comerciais"])

CODE_PATH = Path(..., description="Código HS (2/4/6 dígitos) ou NCM (8 dígitos)", max_length=20)


def _code(raw: str) -> ClassifiedCode:
    try:
        return classify_code(raw)
    except InvalidCodeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _comtrade_context(db, settings, raw_code: str, refresh: bool):
    code = _code(raw_code)
    years = comtrade.default_years()
    meta = comtrade.ensure_imports(db, settings, code.hs_code, years, refresh=refresh)
    df = evolution.load_flows(db, code.hs_code, years)
    warnings = list(meta["warnings"])
    if code.code_type == "NCM":
        warnings.append(
            f"A UN Comtrade usa o padrão internacional HS6; os dados se referem ao HS {code.hs_code}, "
            f"que pode incluir outras NCMs além de {code.code_digits}."
        )
    if df.empty:
        warnings.append("A UN Comtrade não tem registros de importação para este código no período.")
    return code, years, meta, df, warnings


def _names_pt(db: sqlite3.Connection) -> dict[str, str]:
    """ISO3 → nome do país em português (tabela do Comex Stat)."""
    return iso3_names_pt(db)


def _envelope(code: ClassifiedCode, meta: dict, warnings: list[str], source: str, **data) -> dict:
    return {
        "data_nature": DataNature.REAL.value,
        "source": source,
        "code": code.code_digits,
        "code_type": code.code_type,
        "hs_code": code.hs_code,
        "fetched_at": meta.get("fetched_at"),
        "from_cache": meta.get("from_cache"),
        "warnings": warnings,
        **data,
    }


@router.get("/trade/{code}/imports")
def world_imports(
    code: str = CODE_PATH,
    year: int | None = Query(None, ge=2000, le=2100, description="Ano do ranking (padrão: último ano completo)"),
    limit: int = Query(50, ge=1, le=300),
    refresh: bool = Query(False, description="Ignorar cache e consultar a API novamente"),
    settings: Settings = Depends(get_settings),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Importações por país (valor em US$, geralmente CIF) para o código HS."""
    c, years, meta, df, warnings = _comtrade_context(db, settings, code, refresh)
    series = evolution.world_series(df, years)

    chosen = year or evolution.latest_complete_year(series) or max(years)
    info = next((s for s in series if s["year"] == chosen), None)
    if info is None:
        raise HTTPException(status_code=422, detail=f"Ano fora do período consultado ({min(years)}–{max(years)}).")
    if not info["complete"] and info["reporters"]:
        warnings.append(
            f"{chosen} ainda está incompleto na UN Comtrade ({info['reporters']} países informaram); "
            "comparações com anos anteriores podem ser enganosas."
        )

    ranking = evolution.importers_ranking(df, chosen) if not df.empty else []
    names_pt = _names_pt(db)
    for item in ranking:
        item["country_pt"] = names_pt.get(item["iso3"])
    return _envelope(
        c, meta, warnings, comtrade.SOURCE,
        year=chosen, years=years, coverage=series,
        total_countries=len(ranking), importers=ranking[:limit],
        value_note="Valor declarado pelo país importador (primaryValue; normalmente CIF), em US$ correntes.",
    )


@router.get("/trade/{code}/evolution")
def world_evolution(
    code: str = CODE_PATH,
    iso3: str | None = Query(None, description="Países separados por vírgula (ex.: USA,DEU). Padrão: 10 maiores."),
    top: int = Query(10, ge=1, le=50),
    refresh: bool = False,
    settings: Settings = Depends(get_settings),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Evolução histórica: total mundial por ano e série de cada país."""
    c, years, meta, df, warnings = _comtrade_context(db, settings, code, refresh)
    series = evolution.world_series(df, years)
    incomplete = [s["year"] for s in series if not s["complete"] and s["reporters"]]
    if incomplete:
        warnings.append(
            f"Ano(s) com cobertura incompleta: {', '.join(map(str, incomplete))}. "
            "Use 'yoy_comparable_pct', que compara apenas países presentes nos dois anos."
        )
    countries = evolution.country_series(
        df, years, iso3=[s.strip() for s in iso3.split(",") if s.strip()] if iso3 else None, top=top
    ) if not df.empty else []
    names_pt = _names_pt(db)
    for item in countries:
        item["country_pt"] = names_pt.get(item["iso3"])
    return _envelope(c, meta, warnings, comtrade.SOURCE, years=years, world=series, countries=countries)


@router.get("/brazil/{code}/exports")
def brazil_exports(
    code: str = CODE_PATH,
    limit: int = Query(50, ge=1, le=300),
    refresh: bool = False,
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Exportações brasileiras por ano e destino (US$ FOB)."""
    c = _code(code)
    meta = comexstat.ensure_exports(db, c, refresh=refresh)
    warnings = list(meta["warnings"])
    df = comexstat.load_exports(db, c)
    latest_year, latest_month = meta["latest_year"], meta["latest_month"]

    if df.empty:
        warnings.append("O Comex Stat não registra exportações brasileiras deste código no período.")
        return _envelope(c, meta, warnings, comexstat.SOURCE, yearly=[], destinations=[],
                         latest_year=latest_year, latest_month=latest_month)

    if latest_month < 12:
        warnings.append(f"{latest_year} é parcial: dados de janeiro a {latest_month:02d}/{latest_year}.")
    unmapped = sorted(df[df["iso3"].isna()]["country_name"].dropna().unique())
    if unmapped:
        warnings.append(f"Destinos sem código ISO (não cruzam com a Comtrade): {', '.join(unmapped[:10])}.")

    yearly = (
        df.groupby("year")
        .agg(fob_usd=("fob_usd", "sum"), net_weight_kg=("net_weight_kg", "sum"), destinations=("co_pais", "nunique"))
        .reset_index().sort_values("year")
    )
    yearly_out = [
        {"year": int(r.year), "fob_usd": float(r.fob_usd), "net_weight_kg": float(r.net_weight_kg),
         "destinations": int(r.destinations),
         "partial": int(r.year) == latest_year and latest_month < 12}
        for r in yearly.itertuples(index=False)
    ]

    # Ranking de destinos pelo último ano completo, com a série de todos os anos
    ref_year = latest_year - 1 if latest_month < 12 else latest_year
    keyed = df.assign(country_name=df["country_name"].fillna(df["co_pais"]), iso3=df["iso3"].fillna(""))
    pivot = keyed.pivot_table(index=["co_pais", "country_name", "iso3"], columns="year", values="fob_usd",
                              aggfunc="sum").fillna(0)
    pivot = pivot[pivot.sum(axis=1) > 0]
    order = pivot[ref_year] if ref_year in pivot.columns else pivot.sum(axis=1)
    total_ref = float(order.sum())
    destinations = []
    for idx in order.sort_values(ascending=False).index[:limit]:
        co_pais, name, iso = idx
        destinations.append({
            "country": name, "iso3": iso or None,
            "reference_year_fob_usd": float(order[idx]),
            "share_pct": round(float(order[idx]) / total_ref * 100, 2) if total_ref else None,
            "values": [{"year": int(y), "fob_usd": float(pivot.loc[idx, y])} for y in sorted(pivot.columns)],
        })

    return _envelope(
        c, meta, warnings, comexstat.SOURCE,
        latest_year=latest_year, latest_month=latest_month, reference_year=ref_year,
        yearly=yearly_out, total_destinations=len(order[order > 0]), destinations=destinations,
        value_note="Valor FOB em US$ correntes.",
    )
