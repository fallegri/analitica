"""
Extiende la interpretación de chart_advisor con lo específico de pedir una
proyección: a diferencia de un gráfico histórico, siempre necesita una
columna de tiempo, y además hay que extraer (o asumir por defecto) cuántos
períodos hacia adelante proyectar.
"""
import re

from app.services.chart_advisor import ChartInterpretation, interpret_question, validate_ai_result

_FORECAST_KEYWORDS = ["proyect", "predic", "pronostic", "estimar", "estimaci", "futuro", "próximo", "proximo", "siguiente", "que viene"]

_HORIZON_PATTERN = re.compile(r"(\d+)\s*(mes|meses|trimestre|trimestres|año|años|ano|anos|semana|semanas)", re.IGNORECASE)
_UNIT_ONLY_PATTERN = re.compile(r"(pr[oó]xim[oa]|siguiente)\s+(mes|trimestre|año|ano|semana)", re.IGNORECASE)

_PERIODS_PER_UNIT = {"mes": 1, "trimestre": 3, "año": 12, "ano": 12, "semana": 1}


def is_forecast_intent(question: str) -> bool:
    q = question.lower()
    return any(k in q for k in _FORECAST_KEYWORDS)


def _unit_to_periods(unit: str) -> int:
    unit = unit.lower().rstrip("s")  # quitar plural simple: meses->mese (ok para el prefix check de abajo)
    for key, periods in _PERIODS_PER_UNIT.items():
        if unit.startswith(key[:4]):  # "mes","trim","año","sema" alcanzan para distinguir
            return periods
    return 1


def extract_horizon(question: str) -> int:
    q = question.lower()
    m = _HORIZON_PATTERN.search(q)
    if m:
        n = int(m.group(1))
        return max(1, n * _unit_to_periods(m.group(2)))
    m2 = _UNIT_ONLY_PATTERN.search(q)
    if m2:
        return _unit_to_periods(m2.group(2))
    return 3  # sin pista explícita: proyectar 3 períodos (meses) hacia adelante, un valor razonable por defecto


def interpret_forecast_question(
    question: str,
    entries: list[dict],
    df=None,
    ai_result: dict | None = None,
) -> ChartInterpretation:
    base = validate_ai_result(ai_result, entries, df) if ai_result else None
    if base is None:
        base = interpret_question(question, entries, df)

    if base.status == "sin_datos_suficientes":
        return base

    if not base.time_col:
        date_cols = [e["original_header"] for e in entries if e["inferred_type"] == "fecha"]
        if not date_cols:
            return ChartInterpretation(
                status="sin_datos_suficientes",
                explanation=["No encontré ninguna columna de fecha en esta tabla; sin una línea de tiempo no se puede proyectar."],
            )
        if len(date_cols) == 1:
            base.time_col = date_cols[0]
        else:
            base.clarifications.append({
                "field": "time_col",
                "question": "¿Sobre qué columna de fecha querés proyectar?",
                "options": date_cols,
            })
            base.status = "ambiguo"

    if base.status == "ambiguo":
        return base

    base.chart_type = "line"  # una proyección siempre se muestra como serie de tiempo
    return base
