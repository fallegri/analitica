from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.routers.auth_deps import get_current_user
from app.services.auth import ROLE_LABELS, create_token, verify_password
from app.services.users import get_user_by_username

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/auth/login")
async def login(req: LoginRequest):
    user = await get_user_by_username(req.username)
    if not user or not user["active"] or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos.")
    token = create_token(user["id"], user["username"], user["role"])
    return {"token": token, "username": user["username"], "role": user["role"], "role_label": ROLE_LABELS.get(user["role"], user["role"])}


@router.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return {"username": user["username"], "role": user["role"], "role_label": ROLE_LABELS.get(user["role"], user["role"])}
