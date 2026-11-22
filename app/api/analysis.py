"""Motor de análise: ranking de mercados recomendados e detalhe por país (Fase 3)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Path, Query

from app.api.deps import get_db, get_settings
from app.config import Settings
from app.services import analysis, markets

router = APIRouter(prefix="/analysis", tags=["análise de mercados"])

CODE_PATH = Path(..., description="Código HS (2/4/6 dígitos) ou NCM (8 dígitos)", max_length=20)


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
    return markets.build_ranking(db, settings, code, top, year, min_share_pct, refresh)


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
    return markets.build_market_detail(db, settings, code, iso3, year, min_share_pct, refresh)
