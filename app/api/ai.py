"""Inteligência artificial (Fase 4): análise por país e relatório executivo."""

from __future__ import annotations

import re
import sqlite3

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import Response

from app.api.deps import get_db, get_settings
from app.config import Settings
from app.services import ai_insights

router = APIRouter(prefix="/ai", tags=["inteligência artificial"])

CODE_PATH = Path(..., description="Código HS (2/4/6 dígitos) ou NCM (8 dígitos)", max_length=20)
PRODUCT_Q = Query(None, max_length=200, description="Nome do produto como o usuário o descreve (opcional)")
FORMAT_Q = Query("json", pattern="^(json|md)$", description="json ou md (download em Markdown)")


def _markdown_download(markdown: str, filename: str) -> Response:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", filename)
    return Response(content=markdown, media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{safe}"'})


@router.get("/{code}/markets/{iso3}")
def country_analysis(
    code: str = CODE_PATH,
    iso3: str = Path(..., min_length=3, max_length=3),
    product: str | None = PRODUCT_Q,
    refresh: bool = Query(False, description="Gerar novamente, ignorando o cache"),
    format: str = FORMAT_Q,
    settings: Settings = Depends(get_settings),
    db: sqlite3.Connection = Depends(get_db),
):
    """Análise de um mercado com oportunidades, riscos, estratégia e recomendações (IA)."""
    result = ai_insights.country_analysis(db, settings, code, iso3, product, refresh)
    if format == "md":
        return _markdown_download(result["markdown"], f"analise_{result['code']}_{result['market']['iso3']}.md")
    return result


@router.get("/{code}/report")
def executive_report(
    code: str = CODE_PATH,
    product: str | None = PRODUCT_Q,
    top: int = Query(8, ge=3, le=15, description="Quantos mercados do ranking a IA considera"),
    refresh: bool = Query(False, description="Gerar novamente, ignorando o cache"),
    format: str = FORMAT_Q,
    settings: Settings = Depends(get_settings),
    db: sqlite3.Connection = Depends(get_db),
):
    """Relatório executivo de oportunidades de exportação (IA sobre o ranking CFI)."""
    result = ai_insights.executive_report(db, settings, code, product, top, refresh)
    if format == "md":
        return _markdown_download(result["markdown"], f"relatorio_{result['code']}.md")
    return result
