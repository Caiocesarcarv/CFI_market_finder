"""Tabelas oficiais (NCM, países) e interpretação de produto → código com IA."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import get_db, get_settings
from app.config import Settings
from app.models import DataNature
from app.services import ncm_ai, reference

router = APIRouter(tags=["referência e IA"])


@router.get("/reference/status")
def reference_status(db: sqlite3.Connection = Depends(get_db)) -> dict:
    return reference.reference_status(db)


@router.post("/reference/sync", status_code=status.HTTP_202_ACCEPTED)
def reference_sync(settings: Settings = Depends(get_settings)) -> dict:
    """Baixa novamente as tabelas NCM e de países (em segundo plano)."""
    started = reference.start_sync_in_background(settings.database_path)
    return {"started": started, "message": "Sincronização iniciada." if started else "Já existe uma sincronização em andamento."}


@router.get("/ncm/search")
def ncm_search(
    q: str = Query(..., min_length=2, max_length=200),
    limit: int = Query(20, ge=1, le=100),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Busca textual (ou por prefixo numérico) na tabela oficial NCM."""
    return {
        "data_nature": DataNature.REAL.value,
        "source": "Tabela NCM oficial (Comex Stat)",
        "ready": reference.is_ready(db),
        "results": reference.search_ncm(db, q, limit),
    }


@router.get("/ncm/{code}")
def ncm_detail(code: str, db: sqlite3.Connection = Depends(get_db)) -> dict:
    digits = "".join(ch for ch in code if ch.isdigit())
    exact = reference.get_ncm(db, digits) if len(digits) == 8 else None
    return {
        "code": digits,
        "found": exact is not None or bool(reference.ncm_by_prefix(db, digits, 1)),
        "ncm": exact,
        "children": [] if exact else reference.ncm_by_prefix(db, digits, 100),
    }


@router.get("/classify")
def classify_product(
    q: str = Query(..., min_length=3, max_length=300, description="Nome/descrição do produto"),
    refresh: bool = False,
    settings: Settings = Depends(get_settings),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Interpreta a descrição do produto e sugere NCMs (IA + validação na tabela oficial)."""
    return ncm_ai.suggest_codes(db, settings, q, refresh=refresh)
