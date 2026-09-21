"""
Extiende la interpretación de chart_advisor con lo específico de pedir una
proyección: a diferencia de un gráfico histórico, siempre necesita una
columna de tiempo, y además hay que extraer (o asumir por defecto) cuántos
períodos hacia adelante proyectar.

Ahora incluye análisis de la serie de tiempo para recomendar método
y soporte para que la IA sugiera el mejor método basado en el perfil
de los datos.
"""
import json
import re
from typing import Optional

import numpy as np

from app.services.chart_advisor import ChartInterpretation, interpret_question, validate_ai_result
from app.services.forecasting import TimeSeriesProfile, profile_time_series, suggest_method, AVAILABLE_METHODS
from app.services.ai_providers import generate_text

_FORECAST_KEYWORDS = ["proyect", "predic", "pronostic", "estimar", "estimaci", "futuro", "próximo", "proximo", "siguiente", "que viene"]

_HORIZON_PATTERN = re.compile(r"(\d+)\s*(mes|meses|trimestre|trimestres|a[ñn]o|a[ñn]os|semana|semanas)", re.IGNORECASE)
_UNIT_ONLY_PATTERN = re.compile(r"(pr[oó]xim[oa]|siguiente)\s+(mes|trimestre|a[ñn]o|ano|semana)", re.IGNORECASE)

_PERIODS_PER_UNIT = {"mes": 1, "trimestre": 3, "año": 12, "ano": 12, "semana": 1}


def is_forecast_intent(question: str) -> bool:
    q = question.lower()
    return any(k in q for k in _FORECAST_KEYWORDS)


def _unit_to_periods(unit: str) -> int:
    unit = unit.lower().rstrip("s")
    for key, periods in _PERIODS_PER_UNIT.items():
        if unit.startswith(key[:4]):
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
    return 3


async def analyze_series_for_ai(labels: list[str], values: list[float], ai_config) -> Optional[dict]:
    """Pide a la IA que analice la serie y recomiende método."""
    try:
        # Preparar resumen de la serie para la IA
        n = len(values)
        if n < 2:
            return None

        # Estadísticas básicas
        y = np.array(values)
        diff = np.diff(y)
        trend_dir = "creciente" if np.mean(diff) > 0 else "decreciente" if np.mean(diff) < 0 else "estable"
        cv = float(np.std(y) / (np.mean(y) + 1e-9))  # coeficiente de variación

        # Detectar posibles estacionalidades
        seasonal_hints = []
        for p in [4, 12]:  # trimestral, anual
            if n >= 2 * p:
                y1, y2 = y[:-p], y[p:]
                if len(y1) > 2:
                    acf = float(np.corrcoef(y1, y2)[0, 1])
                    if acf > 0.3:
                        seasonal_hints.append(f"posible ciclo de {p} períodos (ACF={acf:.2f})")

        summary = {
            "n_obs": n,
            "rango": f"{min(y):.1f} - {max(y):.1f}",
            "media": round(float(np.mean(y)), 2),
            "std": round(float(np.std(y)), 2),
            "cv": round(cv, 3),
            "tendencia_general": trend_dir,
            "pistas_estacionales": seasonal_hints,
            "primeros_5": [round(v, 2) for v in y[:5]],
            "ultimos_5": [round(v, 2) for v in y[-5:]],
        }

        methods_desc = "\n".join([f"- {m['id']}: {m['label']} - {m['description']}" for m in AVAILABLE_METHODS])

        prompt = (
            "Eres un experto en forecasting de series de tiempo. Analiza esta serie y recomienda "
            "el mejor método de proyección entre las opciones disponibles.\n\n"
            f"Resumen de la serie:\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n\n"
            f"Métodos disponibles:\n{methods_desc}\n\n"
            "Responde SOLO con un JSON válido con esta estructura:\n"
            "{\n"
            '  "recommended_method": "id_del_metodo",\n'
            '  "confidence": 0.85,\n'
            '  "reasoning": "explicación breve en español de por qué este método",\n'
            '  "alternatives": ["id_alt1", "id_alt2"],\n'
            '  "warnings": ["advertencia si aplica"]\n'
            "}"
        )

        from app.services.ai_providers import generate_text
        response = await generate_text(ai_config, prompt)
        if not response:
            return None

        # Extraer JSON de la respuesta
        try:
            start = response.find("{")
            end = response.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(response[start:end])
        except Exception:
            pass
    except Exception:
        pass
    return None


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

    base.chart_type = "line"
    return base


def get_method_recommendation(
    labels: list[str],
    values: list[float],
    user_method: Optional[str] = None,
) -> dict:
    """
    Obtiene recomendación de método basada en perfil estadístico.
    Si user_method se provee, valida compatibilidad.
    """
    profile = profile_time_series(labels, values)
    method, reasoning = suggest_method(profile, user_method)

    return {
        "recommended_method": method,
        "profile": {
            "n_obs": profile.n_obs,
            "has_trend": profile.has_trend,
            "trend_strength": profile.trend_strength,
            "has_seasonality": profile.has_seasonality,
            "seasonal_strength": profile.seasonal_strength,
            "seasonal_period": profile.seasonal_period,
            "stationarity": profile.stationarity,
            "noise_level": profile.noise_level,
        },
        "reasoning": reasoning,
        "available_methods": AVAILABLE_METHODS,
    }


async def get_ai_method_recommendation(
    labels: list[str],
    values: list[float],
    ai_config,
    user_method: Optional[str] = None,
) -> Optional[dict]:
    """
    Obtiene recomendación de método usando IA.
    Retorna None si no hay IA o falla.
    """
    ai_analysis = await analyze_series_for_ai(labels, values, ai_config)
    if not ai_analysis:
        return None

    # Validar que el método recomendado existe
    valid_methods = {m["id"] for m in AVAILABLE_METHODS}
    rec = ai_analysis.get("recommended_method")
    if rec not in valid_methods:
        rec = "auto"

    return {
        "recommended_method": rec,
        "confidence": ai_analysis.get("confidence", 0.7),
        "reasoning": ai_analysis.get("reasoning", ""),
        "alternatives": [a for a in ai_analysis.get("alternatives", []) if a in valid_methods],
        "warnings": ai_analysis.get("warnings", []),
        "source": "ai",
    }