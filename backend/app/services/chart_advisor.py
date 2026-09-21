"""
Interpretación de preguntas en lenguaje natural para sugerir un gráfico.
Funciona sin IA (heurística de palabras clave y sinónimos sobre el nombre,
nombre sugerido y descripción de cada columna); si hay un proveedor de IA
configurado, se usa para ayudar a interpretar frases más libres — pero el
resultado de la IA SIEMPRE se valida contra las columnas reales de la
tabla antes de usarse (nunca se confía en un nombre de columna que la IA
haya inventado).

Cuando hay ambigüedad real (2+ columnas igual de plausibles para lo que
se pidió, o ninguna pista clara y hay más de una candidata neutra), se
devuelve una lista de clarificaciones para que la interfaz le pregunte al
usuario en vez de adivinar — siguiendo el mismo principio de "control del
usuario" que ya se usa en la detección de esquema.
"""
import json
import re
from dataclasses import dataclass, field

import pandas as pd

from app.services.ai_providers import AIConfig, generate_text
from app.services.key_detection import is_key_like

_MEASURE_SYNONYMS = {
    "venta": ["venta", "ventas", "vendid"],
    "ingreso_bruto": ["bruto", "ingreso bruto", "venta bruta"],
    "ingreso_neto": ["neto", "liquid", "ingreso neto", "ganancia neta", "utilidad neta"],
    "ganancia": ["ganancia", "utilidad", "beneficio", "margen"],
    "cantidad": ["cantidad", "unidades", "unidad", "volumen", "stock"],
    "precio": ["precio", "costo", "tarifa"],
}
_TIME_SYNONYMS = ["trimestre", "mes", "mensual", "año", "anual", "semana", "dia", "día", "periodo", "período", "fecha", "tiempo", "evolución", "evolucion"]
_GROUP_SYNONYMS = {
    "producto": ["producto", "articulo", "artículo", "item", "ítem"],
    "canal": ["canal", "sucursal", "tienda", "punto de venta"],
    "cliente": ["cliente", "comprador"],
    "region": ["region", "región", "ciudad", "zona", "departamento", "pais", "país"],
    "categoria": ["categoria", "categoría", "rubro", "tipo"],
}


@dataclass
class ColumnCandidate:
    column: str
    label: str
    score: float


@dataclass
class ChartInterpretation:
    status: str  # "resuelto" | "ambiguo" | "sin_datos_suficientes"
    measure: str | None = None
    group_by: str | None = None
    time_col: str | None = None
    chart_type: str | None = None
    aggregation: str = "sum"
    clarifications: list[dict] = field(default_factory=list)
    explanation: list[str] = field(default_factory=list)


def _is_groupable(e: dict) -> bool:
    """Candidata a agrupación: categórica, o texto de baja cardinalidad. No depende
    solo de la etiqueta 'categórico' del perfilado, que en tablas chicas puede
    clasificar una columna de pocos valores distintos como 'texto' por el umbral
    de proporción única/fila (ver profiling.py) — acá lo que importa es si sirve
    para agrupar un gráfico, no la etiqueta exacta del diccionario."""
    if e["inferred_type"] == "categórico":
        return True
    if e["inferred_type"] == "texto" and e.get("unique_count", 9999) <= 30:
        return True
    return False


def _score_columns(entries: list[dict], keywords: list[str], wanted_type: str, df: pd.DataFrame | None) -> list[ColumnCandidate]:
    candidates = []
    for e in entries:
        col = e["original_header"]
        if e["inferred_type"] != wanted_type:
            continue
        if wanted_type == "numérico" and is_key_like(col, df[col] if df is not None else None):
            continue
        haystack = f"{col} {e.get('suggested_name', '')} {e.get('description', '')}".lower()
        score = sum(1 for kw in keywords if kw in haystack)
        candidates.append(ColumnCandidate(column=col, label=e.get("suggested_name", col), score=score))
    return candidates


def _match_measure(question: str, entries: list[dict], df: pd.DataFrame | None) -> list[ColumnCandidate]:
    q = question.lower()
    matched_groups = [g for g, syns in _MEASURE_SYNONYMS.items() if any(s in q for s in syns)]
    keywords = [s for g in matched_groups for s in _MEASURE_SYNONYMS[g]]
    candidates = _score_columns(entries, keywords, "numérico", df)
    scored = [c for c in candidates if c.score > 0]
    return scored if scored else candidates  # sin coincidencia clara: todas las medidas quedan como candidatas neutras


def _match_group_by(question: str, entries: list[dict], df: pd.DataFrame | None) -> list[ColumnCandidate]:
    q = question.lower()
    matched_groups = [g for g, syns in _GROUP_SYNONYMS.items() if any(s in q for s in syns)]
    keywords = [s for g in matched_groups for s in _GROUP_SYNONYMS[g]]
    candidates = []
    for e in entries:
        if not _is_groupable(e):
            continue
        col = e["original_header"]
        if is_key_like(col, df[col] if df is not None else None):
            continue
        haystack = f"{col} {e.get('suggested_name', '')} {e.get('description', '')}".lower()
        score = sum(1 for kw in keywords if kw in haystack)
        candidates.append(ColumnCandidate(column=col, label=e.get("suggested_name", col), score=score))
    scored = [c for c in candidates if c.score > 0]
    return scored if scored else candidates  # ídem: sin pista, todas las agrupables son candidatas neutras


def _match_time(question: str, entries: list[dict]) -> str | None:
    q = question.lower()
    date_cols = [e["original_header"] for e in entries if e["inferred_type"] == "fecha"]
    if not date_cols:
        return None
    if any(s in q for s in _TIME_SYNONYMS):
        return date_cols[0]
    return None


def _suggest_chart_type(measure: str | None, group_by: str | None, time_col: str | None) -> str:
    if time_col and measure:
        return "line"
    if group_by and measure:
        return "bar"
    return "bar"


def interpret_question(question: str, entries: list[dict], df: pd.DataFrame | None = None) -> ChartInterpretation:
    measure_candidates = _match_measure(question, entries, df)
    group_candidates = _match_group_by(question, entries, df)
    time_col = _match_time(question, entries)

    if not measure_candidates:
        return ChartInterpretation(
            status="sin_datos_suficientes",
            explanation=["No encontré ninguna columna numérica graficable como medida en esta tabla."],
        )

    clarifications: list[dict] = []

    top_measure_score = max(c.score for c in measure_candidates)
    tied_measures = [c for c in measure_candidates if c.score == top_measure_score]
    chosen_measure = tied_measures[0].column if len(tied_measures) == 1 else None
    if len(tied_measures) > 1:
        clarifications.append({
            "field": "measure",
            "question": "¿Qué querés medir exactamente?",
            "options": [c.column for c in tied_measures],
        })

    chosen_group = None
    if group_candidates:
        top_group_score = max(c.score for c in group_candidates)
        tied_groups = [c for c in group_candidates if c.score == top_group_score]
        if len(tied_groups) == 1:
            chosen_group = tied_groups[0].column
        elif len(tied_groups) > 1:
            clarifications.append({
                "field": "group_by",
                "question": "¿Cómo querés agruparlo?",
                "options": [c.column for c in tied_groups],
            })

    if clarifications:
        return ChartInterpretation(
            status="ambiguo",
            measure=chosen_measure, group_by=chosen_group, time_col=time_col,
            clarifications=clarifications,
            explanation=["Encontré más de una opción posible; elegí para armar el gráfico correcto."],
        )

    chart_type = _suggest_chart_type(chosen_measure, chosen_group, time_col)
    explanation = [f"Medida: '{chosen_measure}'."]
    if chosen_group:
        explanation.append(f"Agrupado por: '{chosen_group}'.")
    if time_col:
        explanation.append(f"En el tiempo: '{time_col}'.")
    explanation.append(f"Tipo de gráfico sugerido: {chart_type}.")

    return ChartInterpretation(
        status="resuelto", measure=chosen_measure, group_by=chosen_group, time_col=time_col,
        chart_type=chart_type, aggregation="sum", explanation=explanation,
    )


async def ai_assisted_interpret(config: AIConfig, question: str, entries: list[dict]) -> dict | None:
    columns_desc = "; ".join(
        f"{e['original_header']} ({e['inferred_type']}): {e.get('description', '')}" for e in entries
    )
    prompt = (
        f"Columnas disponibles: {columns_desc}\n\n"
        f'Pregunta del usuario: "{question}"\n\n'
        "Respondé SOLO un JSON, sin texto adicional, con esta forma exacta: "
        '{"measure_column": "<nombre exacto de columna o null>", '
        '"group_by_column": "<nombre exacto de columna o null>", '
        '"time_column": "<nombre exacto de columna o null>"}. '
        "Usá null si no aplica o no estás seguro. Los nombres deben ser EXACTAMENTE "
        "iguales a los de la lista de columnas disponibles, nunca inventados."
    )
    raw = await generate_text(config, prompt)
    if not raw:
        return None
    cleaned = raw.strip().strip("`")
    if cleaned.lower().startswith("json"):
        cleaned = cleaned[4:]
    try:
        return json.loads(cleaned)
    except Exception:
        return None


def validate_ai_result(ai_result: dict, entries: list[dict], df: pd.DataFrame | None) -> "ChartInterpretation | None":
    by_name = {e["original_header"]: e for e in entries}
    measure = ai_result.get("measure_column")
    group_by = ai_result.get("group_by_column")
    time_col = ai_result.get("time_column")

    if not measure or measure not in by_name or by_name[measure]["inferred_type"] != "numérico":
        return None
    if is_key_like(measure, df[measure] if df is not None else None):
        return None
    if group_by and (group_by not in by_name or not _is_groupable(by_name[group_by])):
        group_by = None
    if time_col and (time_col not in by_name or by_name[time_col]["inferred_type"] != "fecha"):
        time_col = None

    chart_type = _suggest_chart_type(measure, group_by, time_col)
    explanation = [f"Interpretado por IA — medida: '{measure}'."]
    if group_by:
        explanation.append(f"Agrupado por: '{group_by}'.")
    if time_col:
        explanation.append(f"En el tiempo: '{time_col}'.")
    return ChartInterpretation(
        status="resuelto", measure=measure, group_by=group_by, time_col=time_col,
        chart_type=chart_type, aggregation="sum", explanation=explanation,
    )


def build_chart_data(df: pd.DataFrame, interpretation: ChartInterpretation) -> dict:
    measure = interpretation.measure
    group_by = interpretation.group_by
    time_col = interpretation.time_col

    work = df.copy()
    work["_measure_"] = pd.to_numeric(work[measure], errors="coerce")

    if time_col:
        dates = pd.to_datetime(work[time_col], errors="coerce", dayfirst=True)
        work["_period_"] = dates.dt.to_period("M").astype(str)
        work = work.dropna(subset=["_period_"])
        if group_by:
            pivot = work.groupby(["_period_", group_by])["_measure_"].sum().unstack(fill_value=0).sort_index()
            labels = [str(x) for x in pivot.index.tolist()]
            series = [{"name": str(col), "values": [round(float(v), 2) for v in pivot[col].tolist()]} for col in pivot.columns]
        else:
            grouped = work.groupby("_period_")["_measure_"].sum().sort_index()
            labels = [str(x) for x in grouped.index.tolist()]
            series = [{"name": measure, "values": [round(float(v), 2) for v in grouped.tolist()]}]
    elif group_by:
        grouped = work.groupby(group_by)["_measure_"].sum().sort_values(ascending=False).head(15)
        labels = [str(x) for x in grouped.index.tolist()]
        series = [{"name": measure, "values": [round(float(v), 2) for v in grouped.tolist()]}]
    else:
        labels = [measure]
        series = [{"name": measure, "values": [round(float(work["_measure_"].sum()), 2)]}]

    return {
        "chart_type": interpretation.chart_type,
        "labels": labels,
        "series": series,
        "measure": measure,
        "group_by": group_by,
        "time_col": time_col,
    }
