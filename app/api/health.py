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
                # dica só quando falta a chave
                "note": None if settings.comtrade_configured else "preencha COMTRADE_API_KEY no arquivo .env",
            },
            "comexstat": {
                "configured": True,  # API pública, não exige chave
                "note": None,
            },
            "groq": {
                "configured": settings.groq_configured,
                "note": f"Modelo: {settings.groq_model}" if settings.groq_configured
                        else "preencha GROQ_API_KEY no arquivo .env",
            },
        },
        "data_natures": [n.value for n in DataNature],
    }
