"""Cadastro de produtos/consultas (produto + código HS/NCM)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_db
from app.models import Search, SearchCreate
from app.services import reference
from app.services.classification import ClassifiedCode, InvalidCodeError, classify_code

router = APIRouter(prefix="/searches", tags=["consultas"])


def check_official(db: sqlite3.Connection, c: ClassifiedCode) -> dict:
    """Confere o código na tabela oficial NCM (se ela já estiver carregada).

    Retorna {"checked": bool, "exists": bool|None, "description": str|None}.
    """
    if not reference.is_ready(db):
        return {"checked": False, "exists": None, "description": None}
    if c.code_type == "NCM":
        row = reference.get_ncm(db, c.code_digits)
        return {"checked": True, "exists": row is not None, "description": row["description"] if row else None}
    exists = bool(reference.ncm_by_prefix(db, c.code_digits, 1))
    return {"checked": True, "exists": exists, "description": None}


@router.get("/validate-code")
def validate_code(code: str = Query(..., max_length=20), db: sqlite3.Connection = Depends(get_db)) -> dict:
    """Valida um código sem salvá-lo (usado pelo formulário em tempo real)."""
    try:
        c = classify_code(code)
    except InvalidCodeError as exc:
        return {"valid": False, "message": str(exc)}
    official = check_official(db, c)
    if official["exists"] is False:
        return {"valid": False, "message": f"{c.code_type} {c.code_digits} não existe na tabela oficial NCM."}
    return {"valid": True, "code_type": c.code_type, "code_digits": c.code_digits, "hs_code": c.hs_code,
            "official_checked": official["checked"], "official_description": official["description"]}


@router.post("", response_model=Search, status_code=status.HTTP_201_CREATED)
def create_search(body: SearchCreate, db: sqlite3.Connection = Depends(get_db)) -> dict:
    try:
        c = classify_code(body.code)
    except InvalidCodeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if check_official(db, c)["exists"] is False:
        raise HTTPException(status_code=422, detail=f"{c.code_type} {c.code_digits} não existe na tabela oficial NCM.")

    with db:
        cur = db.execute(
            """INSERT INTO searches (product_name, code_input, code_digits, code_type, hs_code)
               VALUES (?, ?, ?, ?, ?)""",
            (body.product_name.strip(), c.code_input, c.code_digits, c.code_type, c.hs_code),
        )
    row = db.execute("SELECT * FROM searches WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


@router.get("", response_model=list[Search])
def list_searches(
    limit: int = Query(50, ge=1, le=500),
    db: sqlite3.Connection = Depends(get_db),
) -> list[dict]:
    rows = db.execute("SELECT * FROM searches ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


@router.get("/{search_id}", response_model=Search)
def get_search(search_id: int, db: sqlite3.Connection = Depends(get_db)) -> dict:
    row = db.execute("SELECT * FROM searches WHERE id = ?", (search_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Consulta não encontrada.")
    return dict(row)


@router.delete("/{search_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_search(search_id: int, db: sqlite3.Connection = Depends(get_db)) -> None:
    with db:
        cur = db.execute("DELETE FROM searches WHERE id = ?", (search_id,))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Consulta não encontrada.")
