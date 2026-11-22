"""Ponto de entrada da aplicação FastAPI.

Executar:  uvicorn app.main:app --reload      (ou run.bat no Windows)
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import analysis, health, reference, searches, trade
from app.config import FRONTEND_DIR, Settings, load_settings
from app.database import connect, init_db
from app.services import reference as reference_service
from app.services.http import ExternalServiceError

logger = logging.getLogger("cfi")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Cria a aplicação. Recebe Settings opcionais para facilitar os testes."""
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        version = init_db(settings.database_path)
        logger.info("Banco pronto em %s (esquema v%s)", settings.database_path, version)
        if settings.auto_sync_reference:
            conn = connect(settings.database_path)
            try:
                pending = reference_service.needs_sync(conn)
            finally:
                conn.close()
            if pending:
                logger.info("Baixando tabelas oficiais NCM e países em segundo plano...")
                reference_service.start_sync_in_background(settings.database_path)
        yield

    app = FastAPI(
        title="CFI Market Finder",
        version=__version__,
        description="Inteligência de mercados internacionais para exportadores brasileiros.",
        lifespan=lifespan,
    )
    app.state.settings = settings

    @app.exception_handler(ExternalServiceError)
    async def external_error(request: Request, exc: ExternalServiceError) -> JSONResponse:
        # Falha de API externa: mensagem clara, sem dados inventados no lugar.
        logger.warning("Falha externa em %s: %s", request.url.path, exc)
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": f"{exc.source}: {exc.message}", "source": exc.source},
        )

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        # Erros inesperados viram JSON legível em vez de derrubar o frontend.
        logger.exception("Erro não tratado em %s", request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Erro interno no servidor."})

    app.include_router(health.router, prefix="/api")
    app.include_router(searches.router, prefix="/api")
    app.include_router(reference.router, prefix="/api")
    app.include_router(trade.router, prefix="/api")
    app.include_router(analysis.router, prefix="/api")

    # Frontend estático servido pelo próprio FastAPI (montado por último,
    # para não capturar as rotas /api e /docs).
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
    return app


app = create_app()
