"""Status da aplicação, do banco e das integrações configuradas."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app import __version__
from app.api.deps import get_settings
from app.config import Settings
from app.database import check_db, connect
from app.models import DataNature
from app.services.reference import reference_status

router = APIRouter(tags=["status"])


@router.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict:
    """Verifica banco e informa quais integrações têm chave configurada.

    Não chama as APIs externas (teste de conectividade fica para a Fase 2)
    e nunca devolve o valor das chaves.
    """
    db = check_db(settings.database_path)
    ref = None
    if db["ok"]:
        conn = connect(settings.database_path)
        try:
            ref = reference_status(conn)
        finally:
            conn.close()
    return {
        "reference_tables": ref,
        "status": "ok" if db["ok"] else "degradado",
        "version": __version__,
        "database": db,
        "integrations": {
            "comtrade": {
                "configured": settings.comtrade_configured,
                "note": "Chave COMTRADE_API_KEY (ou UNCOMTRADE_KEY) no .env",
            },
            "comexstat": {
                "configured": True,
                "note": "API pública, não exige chave",
            },
            "groq": {
                "configured": settings.groq_configured,
                "note": f"Modelo: {settings.groq_model}",
            },
        },
        "data_natures": [n.value for n in DataNature],
    }
