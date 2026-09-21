from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.routers.auth_deps import require_min_rank
from app.services.ai_providers import load_config
from app.services.chart_advisor import ChartInterpretation, ai_assisted_interpret, build_chart_data
from app.services.data_cache import get_table
from app.services.forecast_advisor import extract_horizon, interpret_forecast_question
from app.services.forecasting import run_forecast
from app.services.history import get_analysis

router = APIRouter()


def _table_label(t: dict) -> str:
    return f"{t['sheet_name']} (tabla {t['table_index'] + 1})"


def _find_table(analysis: dict, table_label: str) -> Optional[dict]:
    return next((t for t in analysis["tables"] if _table_label(t) == table_label), None)


class ForecastQuestionRequest(BaseModel):
    analysis_id: str
    table_label: str
    question: str
    use_ai: bool = False


class ForecastResolveRequest(BaseModel):
    analysis_id: str
    table_label: str
    measure: str
    group_by: Optional[str] = None
    time_col: str
    horizon: int = 3
    method: str = "lineal"


@router.post("/forecast/interpret")
async def forecast_interpret(req: ForecastQuestionRequest, actor: dict = Depends(require_min_rank("report_viewer"))):
    analysis = await get_analysis(req.analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="Análisis no encontrado en el historial.")
    table = _find_table(analysis, req.table_label)
    if table is None:
        raise HTTPException(status_code=404, detail="Tabla no encontrada en ese análisis.")

    df = get_table(req.analysis_id, req.table_label)
    entries = table["dictionary"]

    ai_raw = None
    if req.use_ai:
        ai_config = await load_config()
        if ai_config.provider != "none":
            ai_raw = await ai_assisted_interpret(ai_config, req.question, entries)

    result = interpret_forecast_question(req.question, entries, df, ai_raw)
    horizon = extract_horizon(req.question)

    return {
        "status": result.status,
        "measure": result.measure,
        "group_by": result.group_by,
        "time_col": result.time_col,
        "clarifications": result.clarifications,
        "explanation": result.explanation,
        "horizon": horizon,
    }


@router.post("/forecast/data")
async def forecast_data(req: ForecastResolveRequest, actor: dict = Depends(require_min_rank("report_viewer"))):
    df = get_table(req.analysis_id, req.table_label)
    if df is None:
        raise HTTPException(
            status_code=404,
            detail="No tengo los datos crudos de esta tabla en memoria. Volvé a analizar el archivo para poder proyectar.",
        )

    historical = build_chart_data(
        df,
        ChartInterpretation(status="resuelto", measure=req.measure, group_by=req.group_by, time_col=req.time_col, chart_type="line", aggregation="sum"),
    )

    if len(historical["labels"]) < 2:
        raise HTTPException(status_code=400, detail="Hay muy pocos períodos históricos para proyectar una tendencia confiable.")

    horizon = max(1, min(req.horizon, 24))  # límite razonable para no proyectar a un plazo absurdo
    series_out = []
    for s in historical["series"]:
        fc = run_forecast(historical["labels"], s["values"], horizon, req.method)
        series_out.append({
            "name": s["name"],
            "historical_labels": fc.historical_labels,
            "historical_values": fc.historical_values,
            "forecast_labels": fc.forecast_labels,
            "forecast_values": fc.forecast_values,
            "lower_bound": fc.lower_bound,
            "upper_bound": fc.upper_bound,
        })

    return {"method": req.method, "measure": req.measure, "group_by": req.group_by, "horizon": horizon, "series": series_out}
