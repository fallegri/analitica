from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.routers.auth_deps import require_min_rank
from app.services.auth import ROLE_LABELS, ROLES
from app.services.users import create_user, delete_user, get_user_by_id, get_user_by_username, list_users, update_user

router = APIRouter()

_MANAGEABLE_BY_ADMIN = {"analista", "report_viewer"}


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str


class UpdateUserRequest(BaseModel):
    role: Optional[str] = None
    active: Optional[bool] = None
    password: Optional[str] = None


def _check_can_manage(actor: dict, target_role: str) -> None:
    if actor["role"] == "super_admin":
        return
    if actor["role"] == "admin" and target_role in _MANAGEABLE_BY_ADMIN:
        return
    raise HTTPException(status_code=403, detail="No tenés permiso para gestionar usuarios con ese rol.")


@router.get("/users/roles")
async def get_roles(actor: dict = Depends(require_min_rank("admin"))):
    return [{"id": r, "label": ROLE_LABELS[r]} for r in ROLES]


@router.get("/users")
async def get_users(actor: dict = Depends(require_min_rank("admin"))):
    return await list_users()


@router.post("/users")
async def post_user(req: CreateUserRequest, actor: dict = Depends(require_min_rank("admin"))):
    if req.role not in ROLES:
        raise HTTPException(status_code=400, detail="Rol inválido.")
    _check_can_manage(actor, req.role)
    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="La contraseña debe tener al menos 8 caracteres.")
    if await get_user_by_username(req.username):
        raise HTTPException(status_code=400, detail="Ese nombre de usuario ya existe.")
    return await create_user(req.username, req.password, req.role)


@router.patch("/users/{user_id}")
async def patch_user(user_id: str, req: UpdateUserRequest, actor: dict = Depends(require_min_rank("admin"))):
    target = await get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    _check_can_manage(actor, target["role"])
    if req.role:
        if req.role not in ROLES:
            raise HTTPException(status_code=400, detail="Rol inválido.")
        _check_can_manage(actor, req.role)
    if req.password and len(req.password) < 8:
        raise HTTPException(status_code=400, detail="La contraseña debe tener al menos 8 caracteres.")
    await update_user(user_id, role=req.role, active=req.active, password=req.password)
    return {"updated": True}


@router.delete("/users/{user_id}")
async def remove_user(user_id: str, actor: dict = Depends(require_min_rank("admin"))):
    target = await get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    if str(target["id"]) == str(actor["id"]):
        raise HTTPException(status_code=400, detail="No podés eliminar tu propio usuario.")
    _check_can_manage(actor, target["role"])
    await delete_user(user_id)
    return {"deleted": True}
