from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.routers.analyze import run_analysis
from app.routers.auth_deps import require_min_rank
from app.services.cleaning import apply_fixes
from app.services.data_cache import get_table
from app.services.history import get_analysis
from app.services.xlsx_export import dataframes_to_xlsx_bytes

router = APIRouter()


def _table_label(t: dict) -> str:
    return f"{t['sheet_name']} (tabla {t['table_index'] + 1})"


def _find_table(analysis: dict, table_label: str) -> Optional[dict]:
    return next((t for t in analysis["tables"] if _table_label(t) == table_label), None)


class CleanRequest(BaseModel):
    analysis_id: str
    table_label: str
    rule_ids: Optional[list[str]] = None  # None = aplicar todas las corregibles disponibles


class CleanAnalyzeRequest(CleanRequest):
    use_ai: bool = False


async def _run_cleaning(req: CleanRequest):
    analysis = await get_analysis(req.analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="Análisis no encontrado en el historial.")
    table = _find_table(analysis, req.table_label)
    if table is None:
        raise HTTPException(status_code=404, detail="Tabla no encontrada en ese análisis.")

    df = get_table(req.analysis_id, req.table_label)
    if df is None:
        raise HTTPException(
            status_code=404,
            detail="No tengo los datos crudos de esta tabla en memoria. Volvé a analizar el archivo para poder limpiarlo.",
        )

    cleaned_df, applied, not_fixable = apply_fixes(df, table["quality_findings"], req.rule_ids)
    return analysis, table, cleaned_df, applied, not_fixable


@router.post("/clean/apply")
async def clean_apply(req: CleanAnalyzeRequest, actor: dict = Depends(require_min_rank("analista"))):
    df_before = get_table(req.analysis_id, req.table_label)
    rows_before = int(len(df_before)) if df_before is not None else None

    analysis, table, cleaned_df, applied, not_fixable = await _run_cleaning(req)

    sheet_name = table["sheet_name"]
    xlsx_bytes = dataframes_to_xlsx_bytes({sheet_name: cleaned_df})
    cleaned_filename = f"limpio_{analysis['filename']}"
    new_analysis = await run_analysis(cleaned_filename, xlsx_bytes, req.use_ai)

    return {
        "applied": applied,
        "not_auto_fixable": not_fixable,
        "rows_before": rows_before,
        "rows_after": int(len(cleaned_df)),
        "cleaned_analysis": new_analysis.model_dump(),
    }


@router.post("/clean/download")
async def clean_download(req: CleanRequest, actor: dict = Depends(require_min_rank("analista"))):
    analysis, table, cleaned_df, applied, not_fixable = await _run_cleaning(req)
    xlsx_bytes = dataframes_to_xlsx_bytes({table["sheet_name"]: cleaned_df})
    filename = f"limpio_{analysis['filename']}"
    return StreamingResponse(
        iter([xlsx_bytes]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
