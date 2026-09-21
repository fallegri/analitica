"""
Proyección sobre una serie de tiempo ya agregada (la misma forma que
produce build_chart_data en chart_advisor.py cuando hay columna de
tiempo). Dos métodos deterministas, sin dependencias pesadas:

- "lineal": regresión lineal simple (mínimos cuadrados) sobre el índice
  de período. Sirve cuando hay una tendencia sostenida.
- "promedio_movil": promedio de los últimos períodos, proyectado plano
  hacia adelante. Sirve cuando la serie es más estable, sin tendencia clara.

La IA (si está configurada) nunca calcula estos números — solo puede
agregar una lectura en palabras del resultado ya calculado, igual que en
insights.py. Los valores de la proyección siempre salen de acá.
"""
from dataclasses import dataclass

import numpy as np


@dataclass
class ForecastResult:
    method: str
    historical_labels: list[str]
    historical_values: list[float]
    forecast_labels: list[str]
    forecast_values: list[float]
    lower_bound: list[float]
    upper_bound: list[float]


def _next_period_labels(last_label: str, horizon: int) -> list[str]:
    """Los labels históricos vienen como 'YYYY-MM' (período mensual). Genera los siguientes N."""
    try:
        year, month = (int(x) for x in last_label.split("-"))
    except (ValueError, AttributeError):
        return [f"periodo_{i+1}" for i in range(horizon)]
    labels = []
    for _ in range(horizon):
        month += 1
        if month > 12:
            month = 1
            year += 1
        labels.append(f"{year:04d}-{month:02d}")
    return labels


def forecast_moving_average(labels: list[str], values: list[float], horizon: int, window: int = 3) -> ForecastResult:
    window = min(window, len(values)) or 1
    recent = values[-window:]
    avg = float(np.mean(recent))
    std = float(np.std(recent)) if len(recent) > 1 else 0.0

    return ForecastResult(
        method="promedio_movil",
        historical_labels=labels, historical_values=[round(float(v), 2) for v in values],
        forecast_labels=_next_period_labels(labels[-1], horizon),
        forecast_values=[round(avg, 2)] * horizon,
        lower_bound=[round(avg - 1.96 * std, 2)] * horizon,
        upper_bound=[round(avg + 1.96 * std, 2)] * horizon,
    )


def forecast_linear(labels: list[str], values: list[float], horizon: int) -> ForecastResult:
    if len(values) < 2:
        return forecast_moving_average(labels, values, horizon, window=1)

    x = np.arange(len(values))
    y = np.array(values, dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    residuals = y - (slope * x + intercept)
    std = float(np.std(residuals)) if len(residuals) > 1 else 0.0

    future_x = np.arange(len(values), len(values) + horizon)
    forecast_values = (slope * future_x + intercept).tolist()

    return ForecastResult(
        method="lineal",
        historical_labels=labels, historical_values=[round(float(v), 2) for v in values],
        forecast_labels=_next_period_labels(labels[-1], horizon),
        forecast_values=[round(float(v), 2) for v in forecast_values],
        lower_bound=[round(float(v) - 1.96 * std, 2) for v in forecast_values],
        upper_bound=[round(float(v) + 1.96 * std, 2) for v in forecast_values],
    )


def run_forecast(labels: list[str], values: list[float], horizon: int, method: str = "lineal") -> ForecastResult:
    if method == "promedio_movil":
        return forecast_moving_average(labels, values, horizon)
    return forecast_linear(labels, values, horizon)
