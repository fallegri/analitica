"""
Autenticación: hashing de contraseñas y tokens JWT.

Seguridad (OWASP):
- Contraseñas con PBKDF2-HMAC-SHA256, 200k iteraciones, salt aleatorio por
  usuario (sin dependencias binarias extra como bcrypt — pbkdf2 alcanza y
  es stdlib puro, más simple de desplegar en serverless).
- JWT_SECRET DEBE fijarse como variable de entorno en producción (Vercel).
  Si no está seteada, se genera una al azar en memoria del proceso — en
  serverless cada instancia/cold-start podría generar una distinta, lo que
  invalidaría tokens emitidos por otra instancia. Esto rompe el login en
  producción con más de una instancia activa. Ver README para cómo fijarla.
"""
import base64
import hashlib
import hmac
import os
import secrets
import time
from typing import Optional

import jwt

if not os.environ.get("JWT_SECRET"):
    print(
        "[PRISM][ADVERTENCIA] JWT_SECRET no está seteada. Se generó una clave temporal en memoria: "
        "los tokens emitidos ahora dejarán de ser válidos si el proceso se reinicia, y en un entorno "
        "serverless con más de una instancia el login puede fallar de forma intermitente. "
        "Fijá JWT_SECRET como variable de entorno antes de desplegar a producción."
    )
_JWT_SECRET = os.environ.get("JWT_SECRET") or secrets.token_hex(32)
_JWT_ALGO = "HS256"
_JWT_EXPIRY_SECONDS = 60 * 60 * 12  # 12 horas

ROLES = ["super_admin", "admin", "analista", "report_viewer"]
ROLE_RANK = {"report_viewer": 0, "analista": 1, "admin": 2, "super_admin": 3}
ROLE_LABELS = {
    "super_admin": "Super administrador",
    "admin": "Administrador",
    "analista": "Analista",
    "report_viewer": "Visor de reportes",
}


def hash_password(password: str, salt: Optional[bytes] = None) -> str:
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return base64.b64encode(salt).decode() + ":" + base64.b64encode(dk).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_b64, hash_b64 = stored.split(":")
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
    except (ValueError, TypeError):
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return hmac.compare_digest(dk, expected)


def create_token(user_id: str, username: str, role: str) -> str:
    payload = {"sub": str(user_id), "username": username, "role": role, "exp": int(time.time()) + _JWT_EXPIRY_SECONDS}
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGO)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGO])
    except jwt.PyJWTError:
        return None
