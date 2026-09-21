"""
Proyección sobre una serie de tiempo ya agregada. Métodos deterministas
sin dependencias pesadas:

- "lineal": regresión lineal simple (mínimos cuadrados) sobre el índice
  de período. Sirve cuando hay una tendencia sostenida.
- "promedio_movil": promedio de los últimos períodos, proyectado plano
  hacia adelante. Sirve cuando la serie es más estable, sin tendencia clara.
- "suavizado_exponencial": suavizado exponencial simple (SES). Se adapta
  a nivel cambiante sin tendencia ni estacionalidad.
- "suavizado_exponencial_tendencia": Holt's linear trend (doble exponencial).
  Captura nivel + tendencia, sin estacionalidad.
- "descomposicion_aditiva": descomposición aditiva (tendencia + estacionalidad
  + residuo) con proyección de componentes. Útil para series con patrón
  estacional claro.

La IA (si está configurada) nunca calcula estos números — solo puede
agregar una lectura en palabras del resultado ya calculado, igual que en
insights.py. Los valores de la proyección siempre salen de acá.
"""
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class ForecastResult:
    method: str
    historical_labels: list[str]
    historical_values: list[float]
    forecast_labels: list[str]
    forecast_values: list[float]
    lower_bound: list[float]
    upper_bound: list[float]
    confidence: float = 0.8  # nivel de confianza para los intervalos
    metadata: Optional[dict] = None  # params usados, diagnóstico, etc.


@dataclass
class TimeSeriesProfile:
    """Perfil de la serie de tiempo para recomendar método."""
    n_obs: int
    has_trend: bool
    trend_strength: float
    has_seasonality: bool
    seasonal_strength: float
    seasonal_period: Optional[int]
    stationarity: str  # "stationary", "trend_stationary", "non_stationary"
    noise_level: float
    missing_pct: float
    recommended_method: str
    reasoning: list[str]


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


def _forecast_interval(values: list[float], forecast: list[float], confidence: float = 0.95) -> tuple[list[float], list[float]]:
    """Calcula intervalos de predicción basados en residuos históricos."""
    if len(values) < 2:
        return [v for v in forecast], [v for v in forecast]
    residuals = np.array(values[1:]) - np.array(values[:-1])
    std = float(np.std(residuals))
    z = 1.96 if confidence >= 0.95 else 1.645 if confidence >= 0.90 else 1.28
    margin = z * std
    lower = [round(f - margin, 2) for f in forecast]
    upper = [round(f + margin, 2) for f in forecast]
    return lower, upper


def forecast_moving_average(labels: list[str], values: list[float], horizon: int, window: int = 3) -> ForecastResult:
    window = min(window, len(values)) or 1
    recent = values[-window:]
    avg = float(np.mean(recent))
    std = float(np.std(recent)) if len(recent) > 1 else 0.0
    forecast = [avg] * horizon
    lower, upper = _forecast_interval(values, forecast)

    return ForecastResult(
        method="promedio_movil",
        historical_labels=labels,
        historical_values=[round(float(v), 2) for v in values],
        forecast_labels=_next_period_labels(labels[-1], horizon),
        forecast_values=[round(avg, 2)] * horizon,
        lower_bound=lower,
        upper_bound=upper,
        confidence=0.95,
        metadata={"window": window, "avg": round(avg, 2), "std": round(std, 2)},
    )


def forecast_linear(labels: list[str], values: list[float], horizon: int) -> ForecastResult:
    if len(values) < 2:
        return forecast_moving_average(labels, values, horizon, window=1)

    x = np.arange(len(values))
    y = np.array(values, dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    fitted = slope * x + intercept
    residuals = y - fitted
    std = float(np.std(residuals)) if len(residuals) > 1 else 0.0

    future_x = np.arange(len(values), len(values) + horizon)
    forecast_values = (slope * future_x + intercept).tolist()
    lower, upper = _forecast_interval(values, forecast_values)

    return ForecastResult(
        method="lineal",
        historical_labels=labels,
        historical_values=[round(float(v), 2) for v in values],
        forecast_labels=_next_period_labels(labels[-1], horizon),
        forecast_values=[round(float(v), 2) for v in forecast_values],
        lower_bound=lower,
        upper_bound=upper,
        confidence=0.95,
        metadata={"slope": round(slope, 4), "intercept": round(intercept, 2), "r2": round(1 - np.var(residuals) / np.var(y), 4) if np.var(y) > 0 else 0},
    )


def _simple_exp_smoothing(values: list[float], alpha: float = None) -> tuple[list[float], float]:
    """Suavizado exponencial simple. Retorna valores suavizados y alpha óptimo."""
    n = len(values)
    if n < 2:
        return values, 0.3

    # Optimizar alpha por MSE en-sample
    best_alpha, best_mse = 0.3, float("inf")
    for a in np.linspace(0.05, 0.95, 19):
        level = values[0]
        mse = 0.0
        for v in values[1:]:
            level = a * v + (1 - a) * level
            mse += (v - level) ** 2
        if mse < best_mse:
            best_mse, best_alpha = mse, a

    alpha = alpha if alpha is not None else best_alpha
    smoothed = [values[0]]
    level = values[0]
    for v in values[1:]:
        level = alpha * v + (1 - alpha) * level
        smoothed.append(level)
    return smoothed, alpha


def forecast_exp_smoothing(labels: list[str], values: list[float], horizon: int) -> ForecastResult:
    """Suavizado exponencial simple (SES) - sin tendencia ni estacionalidad."""
    if len(values) < 2:
        return forecast_moving_average(labels, values, horizon, window=1)

    smoothed, alpha = _simple_exp_smoothing(values)
    level = smoothed[-1]
    forecast = [level] * horizon
    lower, upper = _forecast_interval(values, forecast)

    return ForecastResult(
        method="suavizado_exponencial",
        historical_labels=labels,
        historical_values=[round(float(v), 2) for v in values],
        forecast_labels=_next_period_labels(labels[-1], horizon),
        forecast_values=[round(level, 2)] * horizon,
        lower_bound=lower,
        upper_bound=upper,
        confidence=0.95,
        metadata={"alpha": round(alpha, 3), "final_level": round(level, 2)},
    )


def _holt_linear(values: list[float], alpha: float = None, beta: float = None) -> tuple[list[float], list[float], float, float]:
    """Holt's linear trend (doble exponencial). Retorna level, trend, alpha, beta."""
    n = len(values)
    if n < 2:
        return [values[0]], [0.0], 0.3, 0.1

    best_params, best_mse = (0.3, 0.1), float("inf")
    for a in np.linspace(0.1, 0.9, 9):
        for b in np.linspace(0.05, 0.5, 5):
            level, trend = values[0], values[1] - values[0]
            mse = 0.0
            for i in range(1, n):
                level_new = a * values[i] + (1 - a) * (level + trend)
                trend_new = b * (level_new - level) + (1 - b) * trend
                level, trend = level_new, trend_new
                mse += (values[i] - level) ** 2
            if mse < best_mse:
                best_mse, best_params = mse, (a, b)

    alpha, beta = (alpha, beta) if alpha is not None and beta is not None else best_params
    level, trend = values[0], values[1] - values[0]
    fitted = [values[0]]
    for i in range(1, n):
        level_new = alpha * values[i] + (1 - alpha) * (level + trend)
        trend_new = beta * (level_new - level) + (1 - beta) * trend
        level, trend = level_new, trend_new
        fitted.append(level + trend)
    return fitted, [trend] * n, alpha, beta


def forecast_holt_linear(labels: list[str], values: list[float], horizon: int) -> ForecastResult:
    """Holt's linear trend - captura nivel + tendencia, sin estacionalidad."""
    if len(values) < 3:
        return forecast_linear(labels, values, horizon)

    fitted, trend_vals, alpha, beta = _holt_linear(values)
    level, trend = fitted[-1], trend_vals[-1]
    forecast = [level + trend * (i + 1) for i in range(horizon)]
    lower, upper = _forecast_interval(values, forecast)

    return ForecastResult(
        method="suavizado_exponencial_tendencia",
        historical_labels=labels,
        historical_values=[round(float(v), 2) for v in values],
        forecast_labels=_next_period_labels(labels[-1], horizon),
        forecast_values=[round(float(v), 2) for v in forecast],
        lower_bound=lower,
        upper_bound=upper,
        confidence=0.95,
        metadata={"alpha": round(alpha, 3), "beta": round(beta, 3), "final_level": round(level, 2), "final_trend": round(trend, 4)},
    )


def _seasonal_decompose(values: list[float], period: int) -> tuple[list[float], list[float], list[float]]:
    """Descomposición aditiva simple: tendencia (MA centrada) + estacionalidad + residuo."""
    n = len(values)
    if n < 2 * period:
        # No hay suficientes datos para descomponer
        trend = np.convolve(values, np.ones(min(period, n)) / min(period, n), mode="same").tolist()
        detrended = [v - t for v, t in zip(values, trend)]
        # Estacionalidad promedio por posición en ciclo
        seasonal = [0.0] * n
        for i in range(period):
            idxs = [j for j in range(i, n, period)]
            if len(idxs) > 1:
                s = np.mean([detrended[j] for j in idxs])
                for j in idxs:
                    seasonal[j] = s
        residual = [v - t - s for v, t, s in zip(values, trend, seasonal)]
        return trend, seasonal, residual

    # MA centrada para tendencia
    kernel = np.ones(period) / period
    trend = np.convolve(values, kernel, mode="valid")
    # Pad para igualar longitud
    pad = (n - len(trend)) // 2
    trend = np.pad(trend, (pad, n - len(trend) - pad), mode="edge").tolist()

    detrended = [v - t for v, t in zip(values, trend)]

    # Estacionalidad: promedio por posición en el ciclo
    seasonal = [0.0] * n
    for i in range(period):
        idxs = [j for j in range(i, n, period)]
        if idxs:
            s = np.mean([detrended[j] for j in idxs])
            for j in idxs:
                seasonal[j] = s

    # Normalizar estacionalidad a media cero
    seasonal_mean = np.mean(seasonal)
    seasonal = [s - seasonal_mean for s in seasonal]

    residual = [v - t - s for v, t, s in zip(values, trend, seasonal)]
    return trend, seasonal, residual


def forecast_decomposition(labels: list[str], values: list[float], horizon: int, period: int = 12) -> ForecastResult:
    """Descomposición aditiva + proyección de componentes."""
    if len(values) < 2 * period:
        # Fallback a Holt si no hay suficientes ciclos
        return forecast_holt_linear(labels, values, horizon)

    trend, seasonal, residual = _seasonal_decompose(values, period)

    # Proyectar tendencia con Holt
    trend_fitted, trend_slope, _, _ = _holt_linear(trend)
    last_trend = trend_fitted[-1]
    trend_slope_val = trend_slope[-1]

    # Proyectar estacionalidad repitiendo el último ciclo
    last_seasonal = seasonal[-period:]

    forecast = []
    for i in range(horizon):
        t_proj = last_trend + trend_slope_val * (i + 1)
        s_proj = last_seasonal[i % period]
        forecast.append(t_proj + s_proj)

    lower, upper = _forecast_interval(values, forecast)

    return ForecastResult(
        method="descomposicion_aditiva",
        historical_labels=labels,
        historical_values=[round(float(v), 2) for v in values],
        forecast_labels=_next_period_labels(labels[-1], horizon),
        forecast_values=[round(float(v), 2) for v in forecast],
        lower_bound=lower,
        upper_bound=upper,
        confidence=0.95,
        metadata={"period": period, "trend_slope": round(trend_slope_val, 4), "seasonal_strength": round(float(np.std(seasonal)), 2)},
    )


def profile_time_series(labels: list[str], values: list[float]) -> TimeSeriesProfile:
    """Analiza características de la serie para recomendar método."""
    n = len(values)
    reasoning = []

    if n < 3:
        return TimeSeriesProfile(
            n_obs=n,
            has_trend=False,
            trend_strength=0.0,
            has_seasonality=False,
            seasonal_strength=0.0,
            seasonal_period=None,
            stationarity="insufficient_data",
            noise_level=0.0,
            missing_pct=0.0,
            recommended_method="promedio_movil",
            reasoning=["Muy pocos datos (< 3 puntos). Usando promedio móvil como fallback."],
        )

    # Detección de tendencia (correlación con índice)
    x = np.arange(n)
    y = np.array(values, dtype=float)
    trend_corr = np.corrcoef(x, y)[0, 1] if n > 2 else 0
    has_trend = abs(trend_corr) > 0.3
    if has_trend:
        reasoning.append(f"Tendencia detectada (correlación con tiempo: {trend_corr:.2f}).")

    # Detección de estacionalidad (autocorrelación en lags)
    max_period = min(12, n // 2)
    best_period, best_acf = None, 0.0
    for p in range(2, max_period + 1):
        if n > 2 * p:
            # ACF en lag p
            y1 = y[:-p]
            y2 = y[p:]
            if len(y1) > 2 and len(y2) > 2:
                acf = np.corrcoef(y1, y2)[0, 1]
                if abs(acf) > best_acf:
                    best_acf, best_period = abs(acf), p

    has_seasonality = best_acf > 0.3
    if has_seasonality:
        reasoning.append(f"Estacionalidad detectada (periodo ~{best_period}, ACF={best_acf:.2f}).")

    # Estacionariedad (test simple: varianza de primera diferencia vs original)
    diff = np.diff(y)
    var_ratio = np.var(diff) / (np.var(y) + 1e-9)
    if var_ratio < 0.5:
        stationarity = "stationary"
    elif has_trend and var_ratio < 2.0:
        stationarity = "trend_stationary"
    else:
        stationarity = "non_stationary"

    # Ruido (std de residuos tras quitar tendencia lineal)
    if n > 2:
        slope, intercept = np.polyfit(x, y, 1)
        residuals = y - (slope * x + intercept)
        noise_level = float(np.std(residuals))
    else:
        noise_level = float(np.std(y))

    # Recomendación de método
    if has_seasonality and n >= 2 * best_period:
        method = "descomposicion_aditiva"
        reasoning.append("Serie con estacionalidad clara → descomposición aditiva.")
    elif has_trend and not has_seasonality:
        method = "suavizado_exponencial_tendencia"
        reasoning.append("Serie con tendencia pero sin estacionalidad → Holt's linear trend.")
    elif has_trend and has_seasonality and n < 2 * best_period:
        method = "suavizado_exponencial_tendencia"
        reasoning.append("Tendencia + estacionalidad incipiente (pocos ciclos) → Holt's trend.")
    elif not has_trend and not has_seasonality:
        method = "suavizado_exponencial"
        reasoning.append("Serie estable sin tendencia/estacionalidad → suavizado exponencial simple.")
    else:
        method = "lineal"
        reasoning.append("Patrón mixto → regresión lineal como base.")

    return TimeSeriesProfile(
        n_obs=n,
        has_trend=has_trend,
        trend_strength=abs(float(trend_corr)),
        has_seasonality=has_seasonality,
        seasonal_strength=float(best_acf),
        seasonal_period=best_period,
        stationarity=stationarity,
        noise_level=round(noise_level, 2),
        missing_pct=0.0,
        recommended_method=method,
        reasoning=reasoning,
    )


def suggest_method(profile: TimeSeriesProfile, user_preference: Optional[str] = None) -> tuple[str, list[str]]:
    """Sugiere el mejor método basado en el perfil. Si user_preference dada, valida compatibilidad."""
    if user_preference and user_preference in ["lineal", "promedio_movil", "suavizado_exponencial", "suavizado_exponencial_tendencia", "descomposicion_aditiva"]:
        return user_preference, [f"Usando método solicitado por usuario: {user_preference}"]
    return profile.recommended_method, profile.reasoning


def run_forecast(labels: list[str], values: list[float], horizon: int, method: str = "auto") -> ForecastResult:
    """Ejecuta la proyección. Si method='auto', selecciona automáticamente."""
    if method == "auto":
        profile = profile_time_series(labels, values)
        method, _ = suggest_method(profile)

    methods = {
        "promedio_movil": forecast_moving_average,
        "lineal": forecast_linear,
        "suavizado_exponencial": forecast_exp_smoothing,
        "suavizado_exponencial_tendencia": forecast_holt_linear,
        "descomposicion_aditiva": forecast_decomposition,
    }

    if method not in methods:
        method = "lineal"

    if method == "descomposicion_aditiva":
        # Determinar período estacional
        profile = profile_time_series(labels, values)
        period = profile.seasonal_period or 12
        return methods[method](labels, values, horizon, period=period)
    return methods[method](labels, values, horizon)


AVAILABLE_METHODS = [
    {"id": "auto", "label": "Automático (recomendado por IA)", "description": "Analiza la serie y elige el mejor método"},
    {"id": "lineal", "label": "Regresión lineal", "description": "Tendencia sostenida, crecimiento/decrecimiento constante"},
    {"id": "promedio_movil", "label": "Promedio móvil", "description": "Serie estable, sin tendencia clara"},
    {"id": "suavizado_exponencial", "label": "Suavizado exponencial simple", "description": "Nivel cambiante, sin tendencia ni estacionalidad"},
    {"id": "suavizado_exponencial_tendencia", "label": "Holt's linear trend (doble exponencial)", "description": "Tendencia + nivel cambiante, sin estacionalidad"},
    {"id": "descomposicion_aditiva", "label": "Descomposición aditiva", "description": "Tendencia + estacionalidad clara (requiere ≥ 2 ciclos)"},
]