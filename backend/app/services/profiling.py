"""
Perfilado de columnas. Responsabilidad única: dado un pandas.Series,
devolver estadísticas descriptivas básicas e inferir el tipo de dato.
No genera nombres ni descripciones — eso vive en dictionary.py.
"""
from dataclasses import dataclass
from typing import Any, Optional
import re

import pandas as pd

_DATE_PATTERNS = [
    re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}$"),
    re.compile(r"^\d{4}-\d{1,2}-\d{1,2}$"),
]
_NUMERIC_AS_TEXT = re.compile(r"^-?\d{1,3}([.,]\d{3})*([.,]\d+)?$")


@dataclass
class ColumnProfile:
    inferred_type: str
    non_null_count: int
    null_count: int
    null_pct: float
    unique_count: int
    sample_values: list[Any]
    min_value: Optional[Any]
    max_value: Optional[Any]


def _looks_like_date(sample: pd.Series) -> bool:
    values = sample.dropna().astype(str).str.strip()
    if values.empty:
        return False
    hits = sum(any(p.match(v) for p in _DATE_PATTERNS) for v in values)
    return hits / len(values) > 0.7


def _looks_like_numeric_text(sample: pd.Series) -> bool:
    values = sample.dropna().astype(str).str.strip()
    if values.empty:
        return False
    hits = sum(bool(_NUMERIC_AS_TEXT.match(v)) for v in values)
    return hits / len(values) > 0.7


def infer_type(series: pd.Series) -> str:
    non_null = series.dropna()
    if non_null.empty:
        return "desconocido (columna vacía)"

    numeric_coerced = pd.to_numeric(non_null, errors="coerce")
    if numeric_coerced.notna().mean() > 0.9:
        return "numérico"

    if _looks_like_date(non_null):
        return "fecha"

    if _looks_like_numeric_text(non_null):
        return "numérico expresado como texto"

    unique_ratio = non_null.nunique() / len(non_null)
    if unique_ratio < 0.2 and non_null.nunique() <= 50:
        return "categórico"

    return "texto"


def profile_column(series: pd.Series) -> ColumnProfile:
    non_null = series.dropna()
    inferred = infer_type(series)

    min_v = max_v = None
    if inferred == "numérico":
        numeric = pd.to_numeric(non_null, errors="coerce")
        if not numeric.empty:
            min_v, max_v = float(numeric.min()), float(numeric.max())
    elif inferred == "fecha":
        try:
            parsed = pd.to_datetime(non_null, errors="coerce", dayfirst=True)
            if parsed.notna().any():
                min_v, max_v = str(parsed.min().date()), str(parsed.max().date())
        except Exception:
            pass

    samples = non_null.astype(str).unique()[:5].tolist()

    return ColumnProfile(
        inferred_type=inferred,
        non_null_count=int(non_null.shape[0]),
        null_count=int(series.shape[0] - non_null.shape[0]),
        null_pct=round(100 * (series.shape[0] - non_null.shape[0]) / max(series.shape[0], 1), 1),
        unique_count=int(non_null.nunique()),
        sample_values=samples,
        min_value=min_v,
        max_value=max_v,
    )
