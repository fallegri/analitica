from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.routers.auth_deps import require_min_rank
from app.services.ai_providers import load_config
from app.services.chart_advisor import ChartInterpretation, ai_assisted_interpret, build_chart_data, interpret_question, validate_ai_result
from app.services.data_cache import get_table
from app.services.history import get_analysis

router = APIRouter()


def _table_label(t: dict) -> str:
    return f"{t['sheet_name']} (tabla {t['table_index'] + 1})"


def _find_table(analysis: dict, table_label: str) -> Optional[dict]:
    return next((t for t in analysis["tables"] if _table_label(t) == table_label), None)


class ChartQuestionRequest(BaseModel):
    analysis_id: str
    table_label: str
    question: str
    use_ai: bool = False


class ChartResolveRequest(BaseModel):
    analysis_id: str
    table_label: str
    measure: str
    group_by: Optional[str] = None
    time_col: Optional[str] = None
    chart_type: str
    aggregation: str = "sum"


@router.post("/charts/interpret")
async def charts_interpret(req: ChartQuestionRequest, actor: dict = Depends(require_min_rank("report_viewer"))):
    analysis = await get_analysis(req.analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="Análisis no encontrado en el historial.")
    table = _find_table(analysis, req.table_label)
    if table is None:
        raise HTTPException(status_code=404, detail="Tabla no encontrada en ese análisis.")

    df = get_table(req.analysis_id, req.table_label)
    entries = table["dictionary"]

    result: Optional[ChartInterpretation] = None
    if req.use_ai:
        ai_config = await load_config()
        if ai_config.provider != "none":
            ai_raw = await ai_assisted_interpret(ai_config, req.question, entries)
            if ai_raw:
                result = validate_ai_result(ai_raw, entries, df)

    if result is None:
        result = interpret_question(req.question, entries, df)

    return {
        "status": result.status,
        "measure": result.measure,
        "group_by": result.group_by,
        "time_col": result.time_col,
        "chart_type": result.chart_type,
        "aggregation": result.aggregation,
        "clarifications": result.clarifications,
        "explanation": result.explanation,
    }


@router.post("/charts/data")
async def charts_data(req: ChartResolveRequest, actor: dict = Depends(require_min_rank("report_viewer"))):
    df = get_table(req.analysis_id, req.table_label)
    if df is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "No tengo los datos crudos de esta tabla en memoria (el servidor pudo "
                "haberse reiniciado, o el proceso serverless se recicló). Volvé a "
                "analizar el archivo para poder graficar."
            ),
        )
    interpretation = ChartInterpretation(
        status="resuelto",
        measure=req.measure, group_by=req.group_by, time_col=req.time_col,
        chart_type=req.chart_type, aggregation=req.aggregation,
    )
    return build_chart_data(df, interpretation)
