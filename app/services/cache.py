"""Controle de validade do cache das consultas externas (tabela fetch_log)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_log(conn: sqlite3.Connection, source: str, key: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM fetch_log WHERE source = ? AND query_key = ?", (source, key)
    ).fetchone()
    if row is None:
        return None
    out = dict(row)
    out["meta"] = json.loads(out["meta"]) if out["meta"] else {}
    return out


def is_fresh(log: dict | None, max_age: timedelta) -> bool:
    if not log:
        return False
    fetched = datetime.strptime(log["fetched_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - fetched < max_age


def save_log(conn: sqlite3.Connection, source: str, key: str, records: int, meta: dict | None = None) -> None:
    conn.execute(
        """INSERT INTO fetch_log (source, query_key, status, records, meta, fetched_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(source, query_key) DO UPDATE SET
             status = excluded.status, records = excluded.records,
             meta = excluded.meta, fetched_at = excluded.fetched_at""",
        (source, key, "ok" if records else "empty", records, json.dumps(meta or {}), utcnow_iso()),
    )


def get_cached_payload(conn: sqlite3.Connection, source: str, key: str) -> dict | None:
    """Lê um payload JSON da tabela api_cache, se não estiver expirado."""
    row = conn.execute(
        "SELECT payload, data_nature, fetched_at, expires_at FROM api_cache WHERE source = ? AND cache_key = ?",
        (source, key),
    ).fetchone()
    if row is None:
        return None
    if row["expires_at"] and row["expires_at"] < utcnow_iso():
        return None
    return {"payload": json.loads(row["payload"]), "fetched_at": row["fetched_at"]}


def set_cached_payload(
    conn: sqlite3.Connection, source: str, key: str, payload: dict, data_nature: str, ttl: timedelta
) -> None:
    expires = (datetime.now(timezone.utc) + ttl).strftime("%Y-%m-%dT%H:%M:%SZ")
    with conn:
        conn.execute(
            """INSERT OR REPLACE INTO api_cache (source, cache_key, payload, data_nature, fetched_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (source, key, json.dumps(payload, ensure_ascii=False), data_nature, utcnow_iso(), expires),
        )
