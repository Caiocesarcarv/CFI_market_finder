"""Camada de acesso ao SQLite.

- Usa o módulo sqlite3 da biblioteca padrão (sem ORM).
- O versionamento do esquema usa PRAGMA user_version: cada migração em
  MIGRATIONS é aplicada uma única vez, em ordem.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

# Cada item é aplicado quando user_version < número da migração.
MIGRATIONS: dict[int, str] = {
    1: """
    -- Produtos/consultas cadastrados pelo usuário
    CREATE TABLE IF NOT EXISTS searches (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        product_name  TEXT NOT NULL,
        code_input    TEXT NOT NULL,              -- código como digitado
        code_digits   TEXT NOT NULL,              -- somente dígitos
        code_type     TEXT NOT NULL CHECK (code_type IN ('HS2','HS4','HS6','NCM')),
        hs_code       TEXT NOT NULL,              -- código HS usado nas consultas internacionais (até 6 dígitos)
        created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
    );
    CREATE INDEX IF NOT EXISTS idx_searches_hs ON searches(hs_code);

    -- Cache de respostas das APIs externas (Comtrade, Comex Stat, Groq).
    -- data_nature identifica a natureza do dado: real, estimativa ou demonstrativo.
    CREATE TABLE IF NOT EXISTS api_cache (
        source       TEXT NOT NULL,
        cache_key    TEXT NOT NULL,
        payload      TEXT NOT NULL,               -- JSON
        data_nature  TEXT NOT NULL CHECK (data_nature IN ('real','estimativa','demonstrativo')),
        fetched_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
        expires_at   TEXT,
        PRIMARY KEY (source, cache_key)
    );
    """,
    2: """
    -- Tabela oficial NCM (Comex Stat), usada para validar códigos e sugestões da IA
    CREATE TABLE IF NOT EXISTS ncm (
        co_ncm       TEXT PRIMARY KEY,           -- 8 dígitos
        description  TEXT NOT NULL,
        unit         TEXT
    );
    CREATE VIRTUAL TABLE IF NOT EXISTS ncm_fts USING fts5(
        co_ncm UNINDEXED, description, tokenize = 'unicode61 remove_diacritics 2'
    );

    -- Países do Comex Stat com correspondência ISO (para cruzar com a Comtrade)
    CREATE TABLE IF NOT EXISTS countries (
        co_pais  TEXT PRIMARY KEY,               -- código Comex Stat, 3 dígitos ("023")
        name_pt  TEXT NOT NULL,
        iso3     TEXT,                           -- "DEU"
        m49      INTEGER                         -- código numérico ISO/ONU, usado pela Comtrade
    );
    CREATE INDEX IF NOT EXISTS idx_countries_name ON countries(name_pt);
    CREATE INDEX IF NOT EXISTS idx_countries_m49 ON countries(m49);

    -- Situação da sincronização das tabelas de referência
    CREATE TABLE IF NOT EXISTS reference_sync (
        name       TEXT PRIMARY KEY,             -- 'ncm' | 'countries'
        status     TEXT NOT NULL,                -- 'running' | 'ok' | 'error'
        rows       INTEGER,
        message    TEXT,
        updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
    );

    -- Importações anuais (UN Comtrade). Dado REAL.
    CREATE TABLE IF NOT EXISTS comtrade_flows (
        cmd_code       TEXT NOT NULL,            -- código HS consultado (2, 4 ou 6 dígitos)
        year           INTEGER NOT NULL,
        flow           TEXT NOT NULL,            -- 'M' (importação)
        reporter_code  INTEGER NOT NULL,         -- país importador (M49)
        reporter_iso   TEXT,
        reporter_name  TEXT,
        partner_code   INTEGER NOT NULL,         -- 0 = Mundo, 76 = Brasil
        value_usd      REAL,                     -- primaryValue (CIF na maioria dos países)
        cif_usd        REAL,
        fob_usd        REAL,
        net_weight_kg  REAL,
        qty            REAL,
        qty_unit       TEXT,
        PRIMARY KEY (cmd_code, year, flow, reporter_code, partner_code)
    );

    -- Exportações brasileiras por NCM e destino (Comex Stat). Dado REAL.
    CREATE TABLE IF NOT EXISTS comexstat_exports (
        co_ncm        TEXT NOT NULL,
        year          INTEGER NOT NULL,
        co_pais       TEXT NOT NULL,             -- código Comex Stat (ou nome, se não mapeado)
        country_name  TEXT,
        iso3          TEXT,
        fob_usd       REAL NOT NULL,
        net_weight_kg REAL,
        origin        TEXT NOT NULL CHECK (origin IN ('api','csv')),
        PRIMARY KEY (co_ncm, year, co_pais)
    );
    CREATE INDEX IF NOT EXISTS idx_comexstat_year ON comexstat_exports(year);

    -- Registro de cada consulta externa (controla validade do cache e erros)
    CREATE TABLE IF NOT EXISTS fetch_log (
        source      TEXT NOT NULL,
        query_key   TEXT NOT NULL,
        status      TEXT NOT NULL,               -- 'ok' | 'empty'
        records     INTEGER NOT NULL DEFAULT 0,
        meta        TEXT,                        -- JSON com detalhes (ex.: último mês disponível)
        fetched_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
        PRIMARY KEY (source, query_key)
    );
    """,
    3: """
    -- Fase 3: detalhamento por país fornecedor (parceiro) na Comtrade
    ALTER TABLE comtrade_flows ADD COLUMN partner_iso TEXT;
    ALTER TABLE comtrade_flows ADD COLUMN partner_name TEXT;
    CREATE INDEX IF NOT EXISTS idx_flows_year_partner ON comtrade_flows(cmd_code, year, partner_code);
    """,
}

LATEST_SCHEMA_VERSION = max(MIGRATIONS)


def connect(db_path: Path) -> sqlite3.Connection:
    """Abre uma conexão configurada (linhas como dict, chaves estrangeiras ativas)."""
    # check_same_thread=False: o FastAPI pode executar a dependência e a rota
    # em threads diferentes do pool; cada requisição tem sua própria conexão.
    conn = sqlite3.connect(db_path, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def init_db(db_path: Path) -> int:
    """Cria o arquivo do banco (se necessário) e aplica migrações pendentes.

    Retorna a versão do esquema após a inicialização.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    try:
        current = get_schema_version(conn)
        for version in sorted(MIGRATIONS):
            if version > current:
                with conn:  # transação: aplica tudo ou nada
                    conn.executescript(MIGRATIONS[version])
                    conn.execute(f"PRAGMA user_version = {int(version)}")
        return get_schema_version(conn)
    finally:
        conn.close()


def check_db(db_path: Path) -> dict:
    """Verificação rápida de saúde do banco, usada por /api/health."""
    try:
        conn = connect(db_path)
        try:
            conn.execute("SELECT 1").fetchone()
            return {"ok": True, "schema_version": get_schema_version(conn)}
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return {"ok": False, "error": str(exc)}


def iter_connection(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Gerador usado como dependência do FastAPI (uma conexão por requisição)."""
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()
