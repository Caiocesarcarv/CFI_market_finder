"""Configuração da aplicação, lida do arquivo .env na raiz do projeto.

As chaves de API nunca são expostas pela API; apenas se estão configuradas.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Raiz do projeto (pasta que contém app/, frontend/, run.bat ...)
BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"


@dataclass(frozen=True)
class Settings:
    app_host: str
    app_port: int
    database_path: Path
    comtrade_api_key: str | None
    groq_api_key: str | None
    groq_model: str
    # Baixa as tabelas NCM/países em segundo plano ao iniciar (desligado nos testes)
    auto_sync_reference: bool = True

    @property
    def comtrade_configured(self) -> bool:
        return bool(self.comtrade_api_key)

    @property
    def groq_configured(self) -> bool:
        return bool(self.groq_api_key)


def _clean(value: str | None) -> str | None:
    """Trata strings vazias e placeholders do .env.example como ausentes."""
    if value is None:
        return None
    value = value.strip().strip('"').strip("'")
    if not value or value.lower().startswith(("sua_chave", "chave_")):
        return None
    return value


def load_settings() -> Settings:
    """Carrega as configurações do .env (sem sobrescrever variáveis já definidas)."""
    load_dotenv(BASE_DIR / ".env", override=False)

    db_path = Path(os.getenv("DATABASE_PATH", "data/cfi_market_finder.db"))
    if not db_path.is_absolute():
        db_path = BASE_DIR / db_path

    try:
        port = int(os.getenv("APP_PORT", "8000"))
    except ValueError:
        port = 8000

    return Settings(
        app_host=os.getenv("APP_HOST", "127.0.0.1"),
        app_port=port,
        database_path=db_path,
        # UNCOMTRADE_KEY mantido por compatibilidade com baixar_bulk.py
        comtrade_api_key=_clean(os.getenv("COMTRADE_API_KEY") or os.getenv("UNCOMTRADE_KEY")),
        groq_api_key=_clean(os.getenv("GROQ_API_KEY")),
        groq_model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
    )
