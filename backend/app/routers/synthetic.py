import io

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.models.schemas import AnalyzeResponse
from app.routers.analyze import run_analysis
from app.routers.auth_deps import require_min_rank
from app.services.synthetic_data import VARIANTS, generate_variant
from app.services.xlsx_export import dataframes_to_xlsx_bytes

router = APIRouter()


class SyntheticRequest(BaseModel):
    variant: str
    n_records: int | None = None
    seed: int | None = None


@router.get("/synthetic/variants")
async def list_variants(actor: dict = Depends(require_min_rank("report_viewer"))):
    return [
        {"id": vid, "label": spec["label"], "description": spec["description"], "default_n": spec["default_n"]}
        for vid, spec in VARIANTS.items()
    ]


@router.post("/synthetic/download")
async def synthetic_download(req: SyntheticRequest, actor: dict = Depends(require_min_rank("analista"))):
    if req.variant not in VARIANTS:
        raise HTTPException(status_code=400, detail=f"Variante desconocida: {req.variant}")
    sheets = generate_variant(req.variant, req.n_records, req.seed)
    xlsx_bytes = dataframes_to_xlsx_bytes(sheets)
    filename = f"sintetico_{req.variant}.xlsx"
    return StreamingResponse(
        io.BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/synthetic/analyze", response_model=AnalyzeResponse)
async def synthetic_analyze(req: SyntheticRequest, use_ai: bool = False, actor: dict = Depends(require_min_rank("analista"))):
    if req.variant not in VARIANTS:
        raise HTTPException(status_code=400, detail=f"Variante desconocida: {req.variant}")
    sheets = generate_variant(req.variant, req.n_records, req.seed)
    xlsx_bytes = dataframes_to_xlsx_bytes(sheets)
    filename = f"sintetico_{req.variant}.xlsx"
    return await run_analysis(filename, xlsx_bytes, use_ai)
