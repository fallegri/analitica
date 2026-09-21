from fastapi import APIRouter, Depends, HTTPException

from app.routers.auth_deps import require_min_rank
from app.services.history import get_analysis, list_analyses
from app.services.storage import storage_backend

router = APIRouter()


@router.get("/history")
async def get_history(limit: int = 20, actor: dict = Depends(require_min_rank("report_viewer"))):
    return {"storage_backend": storage_backend(), "items": await list_analyses(limit)}


@router.get("/history/{analysis_id}")
async def get_history_item(analysis_id: str, actor: dict = Depends(require_min_rank("report_viewer"))):
    data = await get_analysis(analysis_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Análisis no encontrado en el historial.")
    return data
