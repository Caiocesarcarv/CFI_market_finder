"""Dependências compartilhadas pelas rotas."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

from fastapi import Request

from app.config import Settings
from app.database import iter_connection


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    yield from iter_connection(request.app.state.settings.database_path)
