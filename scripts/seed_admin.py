"""
Setup inicial de la base de datos: crea el esquema (si no existe) y siembra
un usuario super_admin con credenciales fijas, para no depender de la
contraseña aleatoria que la app genera sola en el primer arranque.

Uso:
    export DATABASE_URL="postgresql://usuario:pass@ep-xxxx.neon.tech/dbname?sslmode=require"
    python3 scripts/seed_admin.py

Por defecto crea el usuario 'admin' con la contraseña impresa en el README
de esta entrega (ver sección "Usuarios y roles"). Para usar otras
credenciales, pasalas por variables de entorno antes de correr el script:

    export ADMIN_USERNAME="fer"
    export ADMIN_PASSWORD=
    python3 scripts/seed_admin.py

Es seguro correrlo más de una vez: si el usuario ya existe, no lo toca (no
pisa una contraseña que ya hayas cambiado) y te avisa en pantalla.
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# permite correr el script como `python3 scripts/seed_admin.py` desde la raíz
# del proyecto sin instalar el paquete, reutilizando el mismo hashing que usa
# la app (backend/app/services/auth.py) para que el hash quede 100% compatible.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = ""

SCHEMA_SQL = (Path(__file__).resolve().parent / "schema.sql").read_text()


async def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: falta la variable de entorno DATABASE_URL (el connection string de Neon).")
        sys.exit(1)

    username = os.environ.get("ADMIN_USERNAME", DEFAULT_ADMIN_USERNAME)
    password = os.environ.get("ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)

    import asyncpg
    from app.services.auth import hash_password

    conn = await asyncpg.connect(database_url)
    try:
        print("Creando esquema (si no existe)...")
        await conn.execute(SCHEMA_SQL)
        print("Esquema listo: users, analyses, app_config.")

        existing = await conn.fetchrow("SELECT id, role FROM users WHERE username = $1", username)
        if existing:
            print(f"El usuario '{username}' ya existe (rol actual: {existing['role']}) — no se modificó nada.")
            return

        user_id = uuid.uuid4()
        await conn.execute(
            """
            INSERT INTO users (id, username, password_hash, role, active, created_at)
            VALUES ($1, $2, $3, 'super_admin', true, $4)
            """,
            user_id, username, hash_password(password), datetime.now(timezone.utc),
        )
        print(f"Usuario super_admin '{username}' creado correctamente.")
        if not DEFAULT_ADMIN_PASSWORD and not os.environ.get("ADMIN_PASSWORD"):
            print("ADVERTENCIA: No se proveyó ADMIN_PASSWORD. Se usó una contraseña vacía — cámbiala inmediatamente.")
        elif password == DEFAULT_ADMIN_PASSWORD:
            print(f"Contraseña (la del README, cámbiala apenas ingreses): {password}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
