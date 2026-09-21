"""
Persistencia de configuración. En Vercel el filesystem es efímero (solo
/tmp, y no se comparte entre invocaciones de la función serverless), así
que un archivo JSON local no sirve ahí para nada que deba sobrevivir entre
requests. Esta capa resuelve el backend automáticamente:

- Si existe la variable de entorno DATABASE_URL (como la que da Neon),
  usa una tabla Postgres simple de clave/valor.
- Si no existe (desarrollo local sin Postgres a mano), usa un archivo
  JSON en disco, igual que antes.

El resto del código (ai_providers.py) no necesita saber cuál de los dos
está activo — solo llama a get_json / set_json.
"""
import json
import os
from pathlib import Path
from typing import Any, Optional

_DATABASE_URL = os.environ.get("DATABASE_URL")
_LOCAL_DIR = Path(__file__).resolve().parent.parent / "data"
# Directorio se crea perezosamente solo si se usa almacenamiento local (sin DATABASE_URL)
_pool = None


def _ensure_local_dir() -> None:
    """Crea el directorio para almacenamiento local solo cuando se usa."""
    if not _DATABASE_URL:
        _LOCAL_DIR.mkdir(parents=True, exist_ok=True)


async def _get_pool():
    global _pool
    if _pool is None:
        import asyncpg  # import perezoso: no hace falta instalarlo si no se usa Postgres
        _pool = await asyncpg.create_pool(_DATABASE_URL, min_size=1, max_size=3)
        async with _pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS app_config (
                    key TEXT PRIMARY KEY,
                    value JSONB NOT NULL,
                    updated_at TIMESTAMPTZ DEFAULT now()
                )
                """
            )
    return _pool


async def close_pool() -> None:
    """Cierra el pool de conexiones (útil en shutdown de FastAPI/Vercel)."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def get_json(key: str) -> Optional[Any]:
    if _DATABASE_URL:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT value FROM app_config WHERE key = $1", key)
            return json.loads(row["value"]) if row else None
    else:
        _ensure_local_dir()
        path = _LOCAL_DIR / f"{key}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except Exception:
            return None


async def set_json(key: str, value: Any) -> None:
    if _DATABASE_URL:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO app_config (key, value, updated_at) VALUES ($1, $2, now())
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
                """,
                key, json.dumps(value),
            )
    else:
        _ensure_local_dir()
        path = _LOCAL_DIR / f"{key}.json"
        path.write_text(json.dumps(value))


def storage_backend() -> str:
    return "neon_postgres" if _DATABASE_URL else "archivo_local"
