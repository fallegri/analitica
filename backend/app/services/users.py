"""
Gestión de usuarios y roles. Mismo criterio de persistencia que
history.py: Neon/Postgres si hay DATABASE_URL, SQLite local si no.

Jerarquía de roles (ROLE_RANK en auth.py): super_admin > admin > analista
> report_viewer. Un admin puede gestionar analista/report_viewer pero
nunca a otro admin ni al super_admin — la validación de jerarquía vive en
los routers (auth_deps.py), acá solo el CRUD.
"""
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.services.auth import hash_password

_DATABASE_URL = os.environ.get("DATABASE_URL")
_SQLITE_PATH = Path(__file__).resolve().parent.parent / "data" / "users.db"
_SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)

_pg_pool = None


async def _get_pg_pool():
    global _pg_pool
    if _pg_pool is None:
        import asyncpg
        _pg_pool = await asyncpg.create_pool(_DATABASE_URL, min_size=1, max_size=3)
        async with _pg_pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id UUID PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    active BOOLEAN NOT NULL DEFAULT true,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
    return _pg_pool


def _sqlite_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_SQLITE_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
        """
    )
    return conn


def _row_to_dict_sqlite(row) -> dict[str, Any]:
    return {"id": row[0], "username": row[1], "password_hash": row[2], "role": row[3], "active": bool(row[4]), "created_at": row[5]}


async def get_user_by_username(username: str) -> Optional[dict]:
    if _DATABASE_URL:
        pool = await _get_pg_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT id, username, password_hash, role, active, created_at FROM users WHERE username = $1", username)
            return {**dict(row), "id": str(row["id"])} if row else None
    conn = _sqlite_conn()
    row = conn.execute("SELECT id, username, password_hash, role, active, created_at FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return _row_to_dict_sqlite(row) if row else None


async def get_user_by_id(user_id: str) -> Optional[dict]:
    if _DATABASE_URL:
        pool = await _get_pg_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT id, username, password_hash, role, active, created_at FROM users WHERE id = $1", uuid.UUID(user_id))
            return {**dict(row), "id": str(row["id"])} if row else None
    conn = _sqlite_conn()
    row = conn.execute("SELECT id, username, password_hash, role, active, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return _row_to_dict_sqlite(row) if row else None


async def list_users() -> list[dict]:
    if _DATABASE_URL:
        pool = await _get_pg_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, username, role, active, created_at FROM users ORDER BY created_at")
            return [{"id": str(r["id"]), "username": r["username"], "role": r["role"], "active": r["active"], "created_at": r["created_at"].isoformat()} for r in rows]
    conn = _sqlite_conn()
    rows = conn.execute("SELECT id, username, role, active, created_at FROM users ORDER BY created_at").fetchall()
    conn.close()
    return [{"id": r[0], "username": r[1], "role": r[2], "active": bool(r[3]), "created_at": r[4]} for r in rows]


async def count_users() -> int:
    if _DATABASE_URL:
        pool = await _get_pg_pool()
        async with pool.acquire() as conn:
            return await conn.fetchval("SELECT COUNT(*) FROM users")
    conn = _sqlite_conn()
    n = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    conn.close()
    return n


async def create_user(username: str, password: str, role: str) -> dict:
    user_id = str(uuid.uuid4())
    password_hash = hash_password(password)
    created_at = datetime.now(timezone.utc)
    if _DATABASE_URL:
        pool = await _get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO users (id, username, password_hash, role, active, created_at) VALUES ($1,$2,$3,$4,true,$5)",
                uuid.UUID(user_id), username, password_hash, role, created_at,
            )
    else:
        conn = _sqlite_conn()
        conn.execute(
            "INSERT INTO users (id, username, password_hash, role, active, created_at) VALUES (?,?,?,?,1,?)",
            (user_id, username, password_hash, role, created_at.isoformat()),
        )
        conn.commit()
        conn.close()
    return {"id": user_id, "username": username, "role": role, "active": True, "created_at": created_at.isoformat()}


async def update_user(user_id: str, role: Optional[str] = None, active: Optional[bool] = None, password: Optional[str] = None) -> None:
    fields: list[str] = []
    values: list[Any] = []
    if role is not None:
        fields.append("role")
        values.append(role)
    if active is not None:
        fields.append("active")
        values.append(active)
    if password is not None:
        fields.append("password_hash")
        values.append(hash_password(password))
    if not fields:
        return

    if _DATABASE_URL:
        pool = await _get_pg_pool()
        set_clause = ", ".join(f"{f} = ${i + 2}" for i, f in enumerate(fields))
        async with pool.acquire() as conn:
            await conn.execute(f"UPDATE users SET {set_clause} WHERE id = $1", uuid.UUID(user_id), *values)
    else:
        conn = _sqlite_conn()
        set_clause = ", ".join(f"{f} = ?" for f in fields)
        conn.execute(f"UPDATE users SET {set_clause} WHERE id = ?", (*values, user_id))
        conn.commit()
        conn.close()


async def delete_user(user_id: str) -> None:
    if _DATABASE_URL:
        pool = await _get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM users WHERE id = $1", uuid.UUID(user_id))
    else:
        conn = _sqlite_conn()
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        conn.close()


async def ensure_super_admin() -> Optional[str]:
    """
    Si todavía no existe ningún usuario, crea el super_admin inicial. Usa
    SUPER_ADMIN_USERNAME / SUPER_ADMIN_PASSWORD si están seteadas en el
    entorno; si no, genera una contraseña aleatoria y la devuelve (para
    mostrarla una única vez en el log de arranque) — nunca queda guardada
    en texto plano en ningún otro lado.
    """
    if await count_users() > 0:
        return None
    username = os.environ.get("SUPER_ADMIN_USERNAME", "admin")
    password = os.environ.get("SUPER_ADMIN_PASSWORD")
    generated = password is None
    if generated:
        import secrets
        password = secrets.token_urlsafe(12)
    await create_user(username, password, "super_admin")
    return password if generated else None
