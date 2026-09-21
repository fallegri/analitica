"""
Análisis de datos (EDA) a partir de lo que ya sabemos de cada columna
(perfilado + diccionario). Responsabilidad: convertir esas estadísticas en
información útil para la persona — no solo "esta columna es numérica", sino
"esto es lo que se podría analizar con estos datos".

Todo lo de acá es heurística/estadística determinística (sin IA). La
narrativa de IA es una capa aparte (ver generate_ai_narrative) que toma
este resumen ya calculado — nunca las filas crudas — y lo redacta en
lenguaje natural o sugiere próximos análisis. Así el costo de tokens es
chico y controlado, y el resultado heurístico sigue disponible aunque la
IA no esté configurada.
"""
from dataclasses import dataclass, field

import pandas as pd

from app.services.ai_providers import AIConfig, generate_text
from app.services.dictionary import ColumnDictionaryEntry
from app.services.key_detection import is_key_like
from app.services.profiling import ColumnProfile


@dataclass
class NumericStats:
    column: str
    mean: float
    median: float
    std: float
    min: float
    q1: float
    q3: float
    max: float


@dataclass
class CategoryFrequency:
    column: str
    top_values: list[tuple[str, int, float]]  # (valor, cantidad, porcentaje)


@dataclass
class CorrelationPair:
    column_a: str
    column_b: str
    correlation: float
    strength: str  # "fuerte" | "moderada"


@dataclass
class TableInsights:
    numeric_stats: list[NumericStats] = field(default_factory=list)
    category_frequencies: list[CategoryFrequency] = field(default_factory=list)
    correlations: list[CorrelationPair] = field(default_factory=list)
    suggested_analyses: list[str] = field(default_factory=list)
    ai_narrative: str | None = None


def _numeric_stats(df: pd.DataFrame, col: str) -> NumericStats | None:
    numeric = pd.to_numeric(df[col], errors="coerce").dropna()
    if numeric.empty:
        return None
    return NumericStats(
        column=col,
        mean=round(float(numeric.mean()), 2),
        median=round(float(numeric.median()), 2),
        std=round(float(numeric.std() or 0), 2),
        min=round(float(numeric.min()), 2),
        q1=round(float(numeric.quantile(0.25)), 2),
        q3=round(float(numeric.quantile(0.75)), 2),
        max=round(float(numeric.max()), 2),
    )


def _category_frequency(df: pd.DataFrame, col: str, top_n: int = 5) -> CategoryFrequency | None:
    values = df[col].dropna().astype(str)
    if values.empty:
        return None
    counts = values.value_counts().head(top_n)
    total = len(values)
    top = [(str(v), int(c), round(100 * c / total, 1)) for v, c in counts.items()]
    return CategoryFrequency(column=col, top_values=top)


def _correlations(df: pd.DataFrame, measure_cols: list[str]) -> list[CorrelationPair]:
    if len(measure_cols) < 2:
        return []
    numeric_df = df[measure_cols].apply(pd.to_numeric, errors="coerce")
    corr_matrix = numeric_df.corr(numeric_only=True)
    pairs: list[CorrelationPair] = []
    seen = set()
    for a in measure_cols:
        for b in measure_cols:
            if a == b or (b, a) in seen:
                continue
            seen.add((a, b))
            value = corr_matrix.loc[a, b] if a in corr_matrix and b in corr_matrix else None
            if value is None or pd.isna(value):
                continue
            if abs(value) < 0.5:
                continue
            strength = "fuerte" if abs(value) > 0.8 else "moderada"
            pairs.append(CorrelationPair(column_a=a, column_b=b, correlation=round(float(value), 2), strength=strength))
    return pairs


def _suggest_analyses(
    measure_cols: list[str],
    profiles: dict[str, ColumnProfile],
    entries: list[ColumnDictionaryEntry],
    correlations: list[CorrelationPair],
) -> list[str]:
    suggestions: list[str] = []
    date_cols = [e.original_header for e in entries if profiles[e.original_header].inferred_type == "fecha"]
    cat_cols = [e.original_header for e in entries if profiles[e.original_header].inferred_type == "categórico"]

    for date_col in date_cols:
        for num_col in measure_cols:
            suggestions.append(f"Evolución de '{num_col}' a lo largo de '{date_col}' (serie de tiempo).")

    for cat_col in cat_cols:
        for num_col in measure_cols:
            suggestions.append(f"'{num_col}' total o promedio agrupado por '{cat_col}' (comparación entre categorías).")

    for pair in correlations:
        suggestions.append(
            f"Relación {pair.strength} entre '{pair.column_a}' y '{pair.column_b}' (r={pair.correlation}) — "
            f"vale la pena revisar si una explica a la otra."
        )

    if len(cat_cols) >= 2:
        suggestions.append(f"Tabla cruzada entre '{cat_cols[0]}' y '{cat_cols[1]}' para ver combinaciones frecuentes.")

    return suggestions[:8]  # evitar una lista interminable; priorizar las primeras encontradas


def compute_table_insights(
    df: pd.DataFrame,
    entries: list[ColumnDictionaryEntry],
    profiles: dict[str, ColumnProfile],
) -> TableInsights:
    numeric_cols = [e.original_header for e in entries if profiles[e.original_header].inferred_type == "numérico"]
    cat_cols = [e.original_header for e in entries if profiles[e.original_header].inferred_type == "categórico"]
    # columnas numéricas que además no son tipo clave (por nombre o por ser una secuencia
    # entera consecutiva) — no sabemos de antemano cómo se van a llamar los campos, así que
    # is_key_like() combina ambas señales en vez de una lista fija de nombres esperados.
    measure_cols = [c for c in numeric_cols if not is_key_like(c, df[c])]

    numeric_stats = [s for col in numeric_cols if (s := _numeric_stats(df, col))]
    category_frequencies = [f for col in cat_cols if (f := _category_frequency(df, col))]
    correlations = _correlations(df, measure_cols)
    suggested = _suggest_analyses(measure_cols, profiles, entries, correlations)

    return TableInsights(
        numeric_stats=numeric_stats,
        category_frequencies=category_frequencies,
        correlations=correlations,
        suggested_analyses=suggested,
    )


async def generate_ai_narrative(config: AIConfig, table_label: str, insights: TableInsights) -> str | None:
    """
    Le pasa a la IA el RESUMEN ya calculado (nunca las filas crudas) y le pide
    una lectura breve en español: qué dicen estos números y qué otros análisis
    valdría la pena hacer. Devuelve None si la IA no responde.
    """
    stats_summary = "; ".join(
        f"{s.column}: media={s.mean}, mediana={s.median}, min={s.min}, max={s.max}" for s in insights.numeric_stats
    ) or "sin columnas numéricas"
    freq_summary = "; ".join(
        f"{f.column}: top = {', '.join(f'{v} ({p}%)' for v, c, p in f.top_values[:3])}" for f in insights.category_frequencies
    ) or "sin columnas categóricas"
    corr_summary = "; ".join(
        f"{c.column_a}~{c.column_b} (r={c.correlation})" for c in insights.correlations
    ) or "sin correlaciones relevantes"

    prompt = (
        f"Tenés estas estadísticas ya calculadas de la tabla '{table_label}':\n"
        f"Estadísticas numéricas: {stats_summary}\n"
        f"Frecuencias categóricas: {freq_summary}\n"
        f"Correlaciones (|r|>=0.5): {corr_summary}\n\n"
        "En español y en un párrafo breve (máximo 4 oraciones), interpretá qué "
        "dicen estos números en términos de negocio y sugerí 1 o 2 análisis "
        "adicionales concretos que valdría la pena hacer con estos datos. "
        "No inventes cifras que no te di."
    )
    return await generate_text(config, prompt)
