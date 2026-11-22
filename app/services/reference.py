"""Tabelas de referência oficiais obtidas da API do Comex Stat (MDIC).

- NCM: ~13,7 mil códigos com descrição oficial. Usada para validar códigos
  digitados e sugestões da IA, e para busca textual (FTS5).
- Países: código Comex Stat → ISO3 e código numérico M49 (o mesmo da
  UN Comtrade), permitindo cruzar as duas fontes.

A sincronização roda uma única vez (em segundo plano na primeira execução)
e pode ser refeita por POST /api/reference/sync.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
from pathlib import Path

from app.database import connect
from app.services.http import ExternalServiceError, request_json

logger = logging.getLogger("cfi.reference")

COMEXSTAT_API = "https://api-comexstat.mdic.gov.br"
SOURCE = "Comex Stat"

_sync_lock = threading.Lock()

_STOPWORDS = {
    "de", "da", "do", "das", "dos", "em", "para", "com", "sem", "por", "e", "ou", "a", "o",
    "as", "os", "um", "uma", "no", "na", "nos", "nas", "tipo", "produto", "produtos",
}


# ---------------------------------------------------------------- status

def _set_status(conn: sqlite3.Connection, name: str, status: str, rows: int | None = None, message: str | None = None):
    with conn:
        conn.execute(
            """INSERT INTO reference_sync (name, status, rows, message, updated_at)
               VALUES (?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ','now'))
               ON CONFLICT(name) DO UPDATE SET status = excluded.status, rows = excluded.rows,
                 message = excluded.message, updated_at = excluded.updated_at""",
            (name, status, rows, message),
        )


def reference_status(conn: sqlite3.Connection) -> dict:
    status = {r["name"]: dict(r) for r in conn.execute("SELECT * FROM reference_sync")}
    counts = {
        "ncm": conn.execute("SELECT COUNT(*) FROM ncm").fetchone()[0],
        "countries": conn.execute("SELECT COUNT(*) FROM countries WHERE iso3 IS NOT NULL").fetchone()[0],
    }
    return {
        name: {
            "rows": counts[name],
            "status": status.get(name, {}).get("status", "pending" if not counts[name] else "ok"),
            "message": status.get(name, {}).get("message"),
            "updated_at": status.get(name, {}).get("updated_at"),
        }
        for name in counts
    }


def is_ready(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT EXISTS(SELECT 1 FROM ncm)").fetchone()[0] == 1


# ---------------------------------------------------------------- sincronização

def sync_ncm(conn: sqlite3.Connection) -> int:
    """Baixa a tabela NCM completa (uma requisição) e recria a busca textual."""
    _set_status(conn, "ncm", "running")
    try:
        body = request_json("GET", f"{COMEXSTAT_API}/tables/ncm", source=SOURCE,
                            params={"page": 1, "perPage": 20000}, timeout=120)
        items = (body.get("data") or {}).get("list") or []
        rows = [
            (str(i["coNcm"]).zfill(8), (i.get("noNCM") or "").strip(), i.get("unit"))
            for i in items
            if i.get("coNcm")
        ]
        if not rows:
            raise ExternalServiceError(SOURCE, "tabela NCM veio vazia")
        with conn:
            conn.execute("DELETE FROM ncm")
            conn.execute("DELETE FROM ncm_fts")
            conn.executemany("INSERT OR REPLACE INTO ncm (co_ncm, description, unit) VALUES (?, ?, ?)", rows)
            conn.execute("INSERT INTO ncm_fts (co_ncm, description) SELECT co_ncm, description FROM ncm")
        _set_status(conn, "ncm", "ok", len(rows))
        return len(rows)
    except Exception as exc:
        _set_status(conn, "ncm", "error", message=str(exc))
        raise


def sync_countries(conn: sqlite3.Connection) -> int:
    """Baixa a lista de países e o ISO3/M49 de cada um (uma requisição por país,
    somente para os que ainda não têm ISO)."""
    _set_status(conn, "countries", "running")
    try:
        body = request_json("GET", f"{COMEXSTAT_API}/tables/countries", source=SOURCE)
        items = (body.get("data") or {}).get("list") or []
        with conn:
            conn.executemany(
                """INSERT INTO countries (co_pais, name_pt) VALUES (?, ?)
                   ON CONFLICT(co_pais) DO UPDATE SET name_pt = excluded.name_pt""",
                [(str(i["id"]).zfill(3), i["text"]) for i in items if i.get("id")],
            )
        pending = [r[0] for r in conn.execute("SELECT co_pais FROM countries WHERE iso3 IS NULL")]
        failures = 0
        for co_pais in pending:
            try:
                d = request_json("GET", f"{COMEXSTAT_API}/tables/countries/{co_pais}", source=SOURCE,
                                 timeout=30, retries=1).get("data") or {}
            except ExternalServiceError:
                failures += 1
                continue
            iso3 = (d.get("coPaisIsoa3") or "").strip() or None
            m49 = d.get("coPaisIson3")
            m49 = int(m49) if str(m49 or "").isdigit() else None
            with conn:
                conn.execute("UPDATE countries SET iso3 = ?, m49 = ? WHERE co_pais = ?", (iso3, m49, co_pais))
        total = conn.execute("SELECT COUNT(*) FROM countries WHERE iso3 IS NOT NULL").fetchone()[0]
        msg = f"{failures} país(es) sem detalhes; serão tentados na próxima sincronização" if failures else None
        _set_status(conn, "countries", "ok", total, msg)
        return total
    except Exception as exc:
        _set_status(conn, "countries", "error", message=str(exc))
        raise


def sync_all(db_path: Path) -> None:
    """Sincroniza NCM e países (ignora se já houver uma sincronização em andamento)."""
    if not _sync_lock.acquire(blocking=False):
        return
    conn = connect(db_path)
    try:
        for fn in (sync_ncm, sync_countries):
            try:
                fn(conn)
            except Exception:
                logger.exception("Falha na sincronização (%s)", fn.__name__)
    finally:
        conn.close()
        _sync_lock.release()


def start_sync_in_background(db_path: Path) -> bool:
    """Dispara sync_all em uma thread. Retorna False se já estiver rodando."""
    if _sync_lock.locked():
        return False
    threading.Thread(target=sync_all, args=(db_path,), name="reference-sync", daemon=True).start()
    return True


def needs_sync(conn: sqlite3.Connection) -> bool:
    has_ncm = is_ready(conn)
    has_countries = conn.execute("SELECT EXISTS(SELECT 1 FROM countries WHERE iso3 IS NOT NULL)").fetchone()[0]
    pending_countries = conn.execute("SELECT EXISTS(SELECT 1 FROM countries WHERE iso3 IS NULL)").fetchone()[0]
    return not has_ncm or not has_countries or bool(pending_countries)


# ---------------------------------------------------------------- consultas

def get_ncm(conn: sqlite3.Connection, code: str) -> dict | None:
    row = conn.execute("SELECT co_ncm, description, unit FROM ncm WHERE co_ncm = ?", (code,)).fetchone()
    return dict(row) if row else None


def ncm_by_prefix(conn: sqlite3.Connection, prefix: str, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT co_ncm, description, unit FROM ncm WHERE co_ncm LIKE ? ORDER BY co_ncm LIMIT ?",
        (prefix + "%", limit),
    ).fetchall()
    return [dict(r) for r in rows]


def search_ncm(conn: sqlite3.Connection, text: str, limit: int = 20) -> list[dict]:
    """Busca textual na tabela NCM (ignora acentos; ordena por relevância BM25)."""
    digits = re.sub(r"[\s.\-]", "", text)
    if digits.isdigit():
        return ncm_by_prefix(conn, digits, limit)

    tokens = [t for t in re.findall(r"\w+", text.lower()) if len(t) >= 3 and t not in _STOPWORDS]
    if not tokens:
        return []
    # Prefixo (cafe*) para cobrir plural/variações; OR + BM25 prioriza quem casa mais termos.
    query = " OR ".join(f'"{t}"*' for t in tokens[:10])
    rows = conn.execute(
        """SELECT n.co_ncm, n.description, n.unit
           FROM ncm_fts f JOIN ncm n ON n.co_ncm = f.co_ncm
           WHERE ncm_fts MATCH ? ORDER BY bm25(ncm_fts) LIMIT ?""",
        (query, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# O Comex Stat lista territórios e países históricos com o mesmo ISO3 do país
# principal (ex.: Ilhas Canárias → ESP, Alemanha Oriental → DEU). Para exibir
# o nome de um ISO3, usa-se o código Comex Stat do país principal:
CANONICAL_CO_PAIS = {
    "ARE": "244", "BRA": "105", "DEU": "023", "ESP": "245", "GBR": "628", "GGY": "321",
    "KNA": "695", "MYS": "455", "PNG": "545", "PRT": "607", "USA": "249",
}
# "ZZZ" é usado para "Não Declarados", "A Designar", "Bancos Centrais" etc.
NON_COUNTRY_ISO = {"ZZZ"}


def clean_iso3(iso3: str | None) -> str | None:
    return None if not iso3 or iso3 in NON_COUNTRY_ISO else iso3


def country_index(conn: sqlite3.Connection) -> dict[str, dict]:
    """Mapa nome (pt) → {co_pais, iso3, m49}, para dados do Comex Stat que vêm só com o nome."""
    return {
        r["name_pt"]: {"co_pais": r["co_pais"], "iso3": clean_iso3(r["iso3"]), "m49": r["m49"]}
        for r in conn.execute("SELECT co_pais, name_pt, iso3, m49 FROM countries")
    }


def iso3_names_pt(conn: sqlite3.Connection) -> dict[str, str]:
    """ISO3 → nome do país em português (país principal quando o ISO3 se repete)."""
    names: dict[str, str] = {}
    for r in conn.execute("SELECT co_pais, name_pt, iso3 FROM countries WHERE iso3 IS NOT NULL ORDER BY co_pais"):
        iso = clean_iso3(r["iso3"])
        if not iso:
            continue
        canonical = CANONICAL_CO_PAIS.get(iso)
        if canonical is None:
            names.setdefault(iso, r["name_pt"])
        elif r["co_pais"] == canonical:
            names[iso] = r["name_pt"]
    return names
