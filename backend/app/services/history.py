"""
Historial de análisis. Mismo criterio que storage.py (config de IA): si
existe DATABASE_URL (Neon), persiste en Postgres; si no, cae a SQLite
local para desarrollo — así el historial sobrevive sin depender de un
Postgres a mano en la máquina de cada quien.

Guarda el AnalyzeResponse completo como JSON en una sola fila por
análisis. Es un historial navegable, no todavía un modelo relacional
normalizado por tabla/columna — eso sería un paso posterior si hace
falta consultar el diccionario acumulado entre archivos distintos en
vez de por análisis completo.
"""
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_DATABASE_URL = os.environ.get("DATABASE_URL")
_SQLITE_PATH = Path(__file__).resolve().parent.parent / "data" / "history.db"
_SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)

_pg_pool = None


async def _get_pg_pool():
    global _pg_pool
    if _pg_pool is None:
        import asyncpg  # import perezoso, solo hace falta si hay DATABASE_URL
        _pg_pool = await asyncpg.create_pool(_DATABASE_URL, min_size=1, max_size=3)
        async with _pg_pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS analyses (
                    id UUID PRIMARY KEY,
                    filename TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    tables_count INT NOT NULL,
                    findings_count INT NOT NULL,
                    payload JSONB NOT NULL
                )
                """
            )
    return _pg_pool


async def close_pg_pool() -> None:
    """Cierra el pool de conexiones Postgres (shutdown de FastAPI/Vercel)."""
    global _pg_pool
    if _pg_pool is not None:
        await _pg_pool.close()
        _pg_pool = None


def _sqlite_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_SQLITE_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS analyses (
            id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            created_at TEXT NOT NULL,
            tables_count INTEGER NOT NULL,
            findings_count INTEGER NOT NULL,
            payload TEXT NOT NULL
        )
        """
    )
    return conn


async def save_analysis(filename: str, tables_count: int, findings_count: int, payload: dict[str, Any]) -> str:
    analysis_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc)

    if _DATABASE_URL:
        pool = await _get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO analyses (id, filename, created_at, tables_count, findings_count, payload)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                uuid.UUID(analysis_id), filename, created_at, tables_count, findings_count, json.dumps(payload),
            )
    else:
        conn = _sqlite_conn()
        conn.execute(
            "INSERT INTO analyses (id, filename, created_at, tables_count, findings_count, payload) VALUES (?,?,?,?,?,?)",
            (analysis_id, filename, created_at.isoformat(), tables_count, findings_count, json.dumps(payload)),
        )
        conn.commit()
        conn.close()

    return analysis_id


async def list_analyses(limit: int = 20) -> list[dict[str, Any]]:
    if _DATABASE_URL:
        pool = await _get_pg_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, filename, created_at, tables_count, findings_count "
                "FROM analyses ORDER BY created_at DESC LIMIT $1",
                limit,
            )
            return [
                {
                    "id": str(r["id"]), "filename": r["filename"],
                    "created_at": r["created_at"].isoformat(),
                    "tables_count": r["tables_count"], "findings_count": r["findings_count"],
                }
                for r in rows
            ]
    else:
        conn = _sqlite_conn()
        rows = conn.execute(
            "SELECT id, filename, created_at, tables_count, findings_count "
            "FROM analyses ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
        return [
            {"id": r[0], "filename": r[1], "created_at": r[2], "tables_count": r[3], "findings_count": r[4]}
            for r in rows
        ]


async def get_analysis(analysis_id: str) -> Optional[dict[str, Any]]:
    if _DATABASE_URL:
        pool = await _get_pg_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT payload FROM analyses WHERE id = $1", uuid.UUID(analysis_id))
            return json.loads(row["payload"]) if row else None
    else:
        conn = _sqlite_conn()
        row = conn.execute("SELECT payload FROM analyses WHERE id = ?", (analysis_id,)).fetchone()
        conn.close()
        return json.loads(row[0]) if row else None
