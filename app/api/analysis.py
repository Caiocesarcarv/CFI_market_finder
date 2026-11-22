"""Motor de análise: ranking de mercados recomendados e detalhe por país (Fase 3)."""

from __future__ import annotations

import sqlite3

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Path, Query

from app.api.deps import get_db, get_settings
from app.config import Settings
from app.models import DataNature
from app.services import analysis, comexstat, comtrade, evolution
from app.services.classification import ClassifiedCode, InvalidCodeError, classify_code
from app.services.http import ExternalServiceError
from app.services.reference import iso3_names_pt

router = APIRouter(prefix="/analysis", tags=["análise de mercados"])

CODE_PATH = Path(..., description="Código HS (2/4/6 dígitos) ou NCM (8 dígitos)", max_length=20)


def _load_partners(db: sqlite3.Connection, hs_code: str, year: int) -> pd.DataFrame:
    return pd.read_sql_query(
        # As linhas do Brasil (parceiro 76) podem vir da série histórica, gravada sem nome do parceiro
        """SELECT reporter_code, reporter_iso, reporter_name, partner_code,
                  CASE WHEN partner_code = 76 THEN COALESCE(partner_iso, 'BRA') ELSE partner_iso END AS partner_iso,
                  CASE WHEN partner_code = 76 THEN COALESCE(partner_name, 'Brazil') ELSE partner_name END AS partner_name,
                  value_usd
           FROM comtrade_flows WHERE cmd_code = ? AND year = ? AND flow = 'M' AND partner_code != 0""",
        db, params=(hs_code, year),
    )


def _brazil_exports_by_iso(db, code: ClassifiedCode, year: int, refresh: bool, warnings: list[str]) -> dict | None:
    """Exportação brasileira FOB por ISO3 no ano (Comex Stat). Falha não interrompe a análise."""
    try:
        meta = comexstat.ensure_exports(db, code, refresh=refresh)
        warnings.extend(meta["warnings"])
    except ExternalServiceError as exc:
        warnings.append(f"Exportações brasileiras indisponíveis ({exc.message}); a análise usa só a UN Comtrade.")
        return None
    df = comexstat.load_exports(db, code)
    df = df[(df["year"] == year) & df["iso3"].notna()]
    return df.groupby("iso3")["fob_usd"].sum().to_dict()


def _context(db, settings, raw_code: str, refresh: bool, year: int | None):
    try:
        code = classify_code(raw_code)
    except InvalidCodeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    years = comtrade.default_years()
    meta = comtrade.ensure_imports(db, settings, code.hs_code, years, refresh=refresh)
    warnings = list(meta["warnings"])
    flows = evolution.load_flows(db, code.hs_code, years)
    if flows.empty:
        raise HTTPException(status_code=404, detail="A UN Comtrade não tem registros de importação para este código.")
    series = evolution.world_series(flows, years)
    ref_year = year or evolution.latest_complete_year(series)
    if ref_year is None or ref_year not in years:
        raise HTTPException(status_code=422, detail="Não há ano com cobertura suficiente para a análise.")
    info = next(s for s in series if s["year"] == ref_year)
    if not info["complete"]:
        warnings.append(f"{ref_year} ainda está incompleto na UN Comtrade ({info['reporters']} países informaram).")

    try:
        pmeta = comtrade.ensure_partner_detail(db, settings, code.hs_code, ref_year, refresh=refresh)
        warnings.extend(w for w in pmeta["warnings"] if w not in warnings)
    except ExternalServiceError as exc:
        warnings.append(f"Detalhe de fornecedores indisponível ({exc.message}); "
                        "concentração e principais fornecedores ficam de fora da pontuação.")
    partners = _load_partners(db, code.hs_code, ref_year)
    if code.code_type == "NCM":
        warnings.append(
            f"Indicadores internacionais referem-se ao HS {code.hs_code} (padrão da UN Comtrade), "
            f"que pode incluir outras NCMs além de {code.code_digits}."
        )
    return code, years, series, ref_year, flows, partners, warnings, meta


@router.get("/{code}/markets")
def recommended_markets(
    code: str = CODE_PATH,
    top: int = Query(30, ge=1, le=250, description="Quantidade de mercados no ranking"),
    year: int | None = Query(None, ge=2000, le=2100, description="Ano de referência (padrão: último ano completo)"),
    min_share_pct: float = Query(analysis.DEFAULT_MIN_SHARE_PCT, ge=0, le=10,
                                 description="Ignora mercados menores que este % das importações mundiais"),
    refresh: bool = False,
    settings: Settings = Depends(get_settings),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Ranking de mercados recomendados com indicadores e pontuação de atratividade."""
    c, years, series, ref_year, flows, partners, warnings, meta = _context(db, settings, code, refresh, year)
    br_exports = _brazil_exports_by_iso(db, c, ref_year, refresh, warnings)

    names = iso3_names_pt(db)
    result = analysis.rank_markets(flows, partners, series, ref_year, br_exports, min_share_pct, names)
    for m in result["markets"]:
        m["country_pt"] = names.get(m["iso3"])
    glob = analysis.global_suppliers(partners)
    for s in glob["top"] + ([glob["brazil"]] if glob["brazil"] else []):
        s["country_pt"] = names.get(s["iso3"])
    if partners.empty:
        warnings.append("Sem detalhamento por fornecedor; concentração e principais fornecedores indisponíveis.")
    if result["brazil_world_share_pct"] == 0:
        warnings.append("Os importadores não registram compras do Brasil neste código no ano de referência.")

    return {
        "data_nature": DataNature.ESTIMATIVA.value,
        "data_nature_note": "Pontuação e ranking são estimativas da metodologia CFI; "
                            "os indicadores são calculados a partir de dados reais.",
        "source": "Cálculo CFI sobre UN Comtrade" + (" e Comex Stat" if br_exports is not None else ""),
        "code": c.code_digits, "code_type": c.code_type, "hs_code": c.hs_code,
        "reference_year": ref_year, "years": years, "fetched_at": meta["fetched_at"],
        "warnings": warnings,
        "methodology": {
            "weights": analysis.WEIGHTS,
            "indicators": {k: {"label": analysis.LABELS[k], "description": analysis.DESCRIPTIONS[k]}
                           for k in analysis.WEIGHTS},
            "normalization": "Cada indicador vira percentil (0–100) entre os mercados avaliados; "
                             "a pontuação é a média ponderada dos indicadores disponíveis.",
            "min_share_pct": min_share_pct,
            "values": "Importações: valor declarado pelo importador (geralmente CIF). "
                      "Exportações brasileiras (Comex Stat): FOB.",
        },
        "benchmark": {
            "world_imports_usd": result["total_world_usd"],
            "brazil_world_share_pct": result["brazil_world_share_pct"],
            "markets_evaluated": len(result["markets"]),
            "markets_excluded_small": result["excluded_small"],
        },
        "global_suppliers": glob,
        "markets": result["markets"][:top],
    }


@router.get("/{code}/markets/{iso3}")
def market_detail(
    code: str = CODE_PATH,
    iso3: str = Path(..., min_length=3, max_length=3),
    year: int | None = Query(None, ge=2000, le=2100),
    min_share_pct: float = Query(analysis.DEFAULT_MIN_SHARE_PCT, ge=0, le=10),
    refresh: bool = False,
    settings: Settings = Depends(get_settings),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Detalhe de um mercado: indicadores, pontuação, série histórica e todos os fornecedores."""
    c, years, series, ref_year, flows, partners, warnings, meta = _context(db, settings, code, refresh, year)
    br_exports = _brazil_exports_by_iso(db, c, ref_year, refresh, warnings)
    iso3 = iso3.upper()
    names = iso3_names_pt(db)

    # Mesmo critério do ranking principal, para a posição ser comparável
    result = analysis.rank_markets(flows, partners, series, ref_year, br_exports, min_share_pct, names)
    market = next((m for m in result["markets"] if m["iso3"] == iso3), None)
    in_main_ranking = market is not None
    if market is None:  # mercado pequeno: avaliado entre todos, sem filtro de tamanho
        result = analysis.rank_markets(flows, partners, series, ref_year, br_exports, 0, names)
        market = next((m for m in result["markets"] if m["iso3"] == iso3), None)
        if market is None:
            raise HTTPException(status_code=404, detail=f"{iso3} não registra importações deste código em {ref_year}.")
        warnings.append(
            f"Mercado abaixo de {min_share_pct}% das importações mundiais: fora do ranking principal; "
            "posição calculada entre todos os importadores."
        )
    market["country_pt"] = names.get(iso3)

    suppliers = analysis.suppliers_of(partners, market["reporter_code"])
    for s in suppliers:
        s["country_pt"] = names.get(s["iso3"])
    history = evolution.country_series(flows, years, iso3=[iso3])

    return {
        "data_nature": DataNature.ESTIMATIVA.value,
        "data_nature_note": "Pontuação é estimativa da metodologia CFI; indicadores, série e fornecedores são dados reais.",
        "source": "Cálculo CFI sobre UN Comtrade" + (" e Comex Stat" if br_exports is not None else ""),
        "code": c.code_digits, "code_type": c.code_type, "hs_code": c.hs_code,
        "reference_year": ref_year, "fetched_at": meta["fetched_at"], "warnings": warnings,
        "market": market,
        "in_main_ranking": in_main_ranking,
        "rank_among": len(result["markets"]),
        "history": history[0]["values"] if history else [],
        "suppliers": suppliers,
    }
