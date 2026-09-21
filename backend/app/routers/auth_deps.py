from fastapi import Depends, Header, HTTPException

from app.services.auth import ROLE_RANK, decode_token
from app.services.users import get_user_by_id


async def get_current_user(authorization: str = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="No autenticado.")
    token = authorization[len("Bearer "):]
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Token inválido o expirado. Volvé a iniciar sesión.")
    user = await get_user_by_id(payload["sub"])
    if not user or not user["active"]:
        raise HTTPException(status_code=401, detail="Usuario no encontrado o inactivo.")
    return user


def require_min_rank(min_role: str):
    """Exige que el rol del usuario autenticado tenga rango >= min_role en la jerarquía."""
    async def checker(user: dict = Depends(get_current_user)) -> dict:
        if ROLE_RANK.get(user["role"], -1) < ROLE_RANK.get(min_role, 999):
            raise HTTPException(status_code=403, detail="No tenés permiso para esta acción.")
        return user
    return checker
