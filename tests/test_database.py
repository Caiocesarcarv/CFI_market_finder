from app.database import LATEST_SCHEMA_VERSION, check_db, connect, init_db


def test_init_creates_schema(tmp_path):
    db = tmp_path / "sub" / "x.db"
    assert init_db(db) == LATEST_SCHEMA_VERSION
    conn = connect(db)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert {"searches", "api_cache"} <= tables


def test_init_is_idempotent(tmp_path):
    db = tmp_path / "x.db"
    init_db(db)
    conn = connect(db)
    with conn:
        conn.execute(
            "INSERT INTO searches (product_name, code_input, code_digits, code_type, hs_code)"
            " VALUES ('Café', '0901', '0901', 'HS4', '0901')"
        )
    conn.close()
    init_db(db)  # rodar de novo não pode apagar dados
    conn = connect(db)
    assert conn.execute("SELECT COUNT(*) FROM searches").fetchone()[0] == 1
    conn.close()


def test_api_cache_rejects_unknown_data_nature(tmp_path):
    import sqlite3

    import pytest

    db = tmp_path / "x.db"
    init_db(db)
    conn = connect(db)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO api_cache (source, cache_key, payload, data_nature) VALUES ('x','k','{}','inventado')"
        )
    conn.close()


def test_check_db(tmp_path):
    db = tmp_path / "x.db"
    init_db(db)
    assert check_db(db) == {"ok": True, "schema_version": LATEST_SCHEMA_VERSION}
