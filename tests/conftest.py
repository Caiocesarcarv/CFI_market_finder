"""Fixtures: cada teste usa um banco SQLite temporário e chaves fictícias."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def make_settings(tmp_path, comtrade=None, groq=None) -> Settings:
    return Settings(
        app_host="127.0.0.1",
        app_port=8000,
        database_path=tmp_path / "test.db",
        comtrade_api_key=comtrade,
        groq_api_key=groq,
        groq_model="modelo-teste",
        auto_sync_reference=False,  # testes nunca acessam a rede
    )


@pytest.fixture
def client(tmp_path):
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as c:  # "with" dispara o lifespan (init_db)
        yield c
