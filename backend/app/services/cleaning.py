"""
Transformaciones para corregir hallazgos de calidad que tienen un arreglo
razonablemente no ambiguo. Cada función recibe el DataFrame y la columna
afectada, y devuelve (df_modificado, mensaje explicando qué se hizo) —
nunca modifica en el lugar sin dejar constancia de lo que cambió.

Los hallazgos que son un conflicto de criterio de negocio — precios o
códigos inconsistentes, donde no hay forma de saber cuál valor es el
correcto sin contexto humano — NO tienen arreglo automático acá a
propósito. Corregirlos a ciegas podría introducir un error peor que el
original; quedan para revisión manual, siguiendo el mismo principio de
"control del usuario" que ya rige en la detección de esquema.
"""
import difflib

import pandas as pd

from app.services.quality.abbreviations import _CITY_MAP
from app.services.quality.encoding import _MOJIBAKE_MARKERS


def fix_duplicates(df: pd.DataFrame, column: str | None = None) -> tuple[pd.DataFrame, str]:
    before = len(df)
    cleaned = df.drop_duplicates(keep="first").reset_index(drop=True)
    removed = before - len(cleaned)
    return cleaned, f"Se eliminaron {removed} fila(s) duplicada(s), se conservó la primera aparición de cada una."


def fix_nulls(df: pd.DataFrame, column: str) -> tuple[pd.DataFrame, str]:
    cleaned = df.copy()
    series = cleaned[column]
    n_nulls = int(series.isna().sum())
    if n_nulls == 0:
        return cleaned, f"'{column}' no tenía nulos que imputar."
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().mean() > 0.5:
        fill_value = float(numeric.median())
        cleaned[column] = numeric.fillna(fill_value)
        return cleaned, f"Se imputaron {n_nulls} nulo(s) en '{column}' con la mediana ({fill_value:.2f})."
    mode = series.mode(dropna=True)
    fill_value = mode.iloc[0] if not mode.empty else "Desconocido"
    cleaned[column] = series.fillna(fill_value)
    return cleaned, f"Se imputaron {n_nulls} nulo(s) en '{column}' con el valor más frecuente ('{fill_value}')."


def fix_negatives(df: pd.DataFrame, column: str) -> tuple[pd.DataFrame, str]:
    cleaned = df.copy()
    numeric = pd.to_numeric(cleaned[column], errors="coerce")
    n_neg = int((numeric < 0).sum())
    if n_neg == 0:
        return cleaned, f"'{column}' no tenía valores negativos."
    cleaned[column] = numeric.abs()
    return cleaned, f"Se convirtieron {n_neg} valor(es) negativo(s) en '{column}' a su valor absoluto (asumiendo error de signo en la captura)."


def fix_outliers(df: pd.DataFrame, column: str) -> tuple[pd.DataFrame, str]:
    cleaned = df.copy()
    numeric = pd.to_numeric(cleaned[column], errors="coerce")
    q1, q3 = numeric.quantile(0.25), numeric.quantile(0.75)
    iqr = q3 - q1
    if iqr == 0:
        return cleaned, f"'{column}' no tiene variabilidad suficiente para acotar atípicos."
    lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    n_out = int(((numeric < lower) | (numeric > upper)).sum())
    cleaned[column] = numeric.clip(lower=lower, upper=upper)
    return cleaned, f"Se acotaron {n_out} valor(es) atípico(s) en '{column}' al rango [{lower:.2f}, {upper:.2f}] (winsorización, no se borraron filas)."


def fix_date_format(df: pd.DataFrame, column: str) -> tuple[pd.DataFrame, str]:
    cleaned = df.copy()
    original = cleaned[column]
    parsed = pd.to_datetime(original, errors="coerce", dayfirst=True)

    # Lo que no parseó con dayfirst=True puede venir en mm/dd/yyyy real —
    # reintentar antes de darlo por perdido, para no destruir datos válidos.
    still_null = parsed.isna() & original.notna()
    if still_null.any():
        retry = pd.to_datetime(original[still_null], errors="coerce", dayfirst=False)
        parsed.loc[still_null] = retry

    n_ok = int(parsed.notna().sum())
    n_unparsed = int((parsed.isna() & original.notna()).sum())
    normalized = parsed.dt.strftime("%d/%m/%Y")
    # nunca pisar con vacío un valor que no se pudo interpretar: se deja el original sin tocar
    cleaned[column] = normalized.where(parsed.notna(), original)

    msg = f"Se normalizaron {n_ok} fecha(s) en '{column}' al formato dd/mm/yyyy."
    if n_unparsed:
        msg += f" {n_unparsed} valor(es) no se pudieron interpretar como fecha y se dejaron sin cambios (no se generaron nulos nuevos)."
    return cleaned, msg


def fix_currency(df: pd.DataFrame, column: str) -> tuple[pd.DataFrame, str]:
    cleaned = df.copy()
    values = cleaned[column].astype(str)
    numeric_str = values.str.replace(r"[^\d,.\-]", "", regex=True).str.replace(",", "", regex=False)
    numeric = pd.to_numeric(numeric_str, errors="coerce")
    cleaned[column] = numeric
    return cleaned, f"Se quitaron símbolos/códigos de moneda de '{column}' y quedó como valor numérico puro (sin conversión de tipo de cambio)."


def fix_numeric_as_text(df: pd.DataFrame, column: str) -> tuple[pd.DataFrame, str]:
    cleaned = df.copy()
    numeric = pd.to_numeric(cleaned[column].astype(str).str.replace(",", "", regex=False), errors="coerce")
    cleaned[column] = numeric
    return cleaned, f"Se convirtió '{column}' de texto a valor numérico."


def fix_city_abbrev(df: pd.DataFrame, column: str) -> tuple[pd.DataFrame, str]:
    cleaned = df.copy()

    def normalize(v):
        if pd.isna(v):
            return v
        canonical = _CITY_MAP.get(str(v).strip().lower())
        return canonical.title() if canonical else v

    before_unique = cleaned[column].nunique()
    cleaned[column] = cleaned[column].apply(normalize)
    after_unique = cleaned[column].nunique()
    return cleaned, f"Se uniformaron las variantes de ciudad en '{column}' ({before_unique} → {after_unique} valores distintos)."


def fix_category_consistency(df: pd.DataFrame, column: str) -> tuple[pd.DataFrame, str]:
    """Usa el mismo criterio que el detector (quality/categories.py): coincidencia
    exacta case-insensitive O similaridad >0.85 — sin esto, el fixer podía dejar
    sin resolver justo lo que la regla había marcado como inconsistente."""
    cleaned = df.copy()
    values = cleaned[column].dropna().astype(str)
    uniques = values.unique().tolist()

    parent = {v: v for v in uniques}

    def find(v: str) -> str:
        while parent[v] != v:
            v = parent[v]
        return v

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i, a in enumerate(uniques):
        for b in uniques[i + 1:]:
            if a.lower() == b.lower() or difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio() > 0.85:
                union(a, b)

    groups: dict[str, list[str]] = {}
    for v in uniques:
        groups.setdefault(find(v), []).append(v)

    canonical_by_variant = {}
    for variants in groups.values():
        if len(variants) == 1:
            continue
        counts = values[values.isin(variants)].value_counts()
        canonical_value = counts.idxmax()  # el más frecuente entre las variantes gana
        for v in variants:
            canonical_by_variant[v] = canonical_value

    before_unique = cleaned[column].nunique()
    cleaned[column] = cleaned[column].apply(lambda v: canonical_by_variant.get(str(v), v) if pd.notna(v) else v)
    after_unique = cleaned[column].nunique()
    return cleaned, f"Se uniformaron variantes de categoría en '{column}' usando el valor más frecuente como canónico ({before_unique} → {after_unique} valores distintos)."


def fix_encoding(df: pd.DataFrame, column: str) -> tuple[pd.DataFrame, str]:
    cleaned = df.copy()

    def has_mojibake(v) -> bool:
        return pd.notna(v) and any(m in str(v) for m in _MOJIBAKE_MARKERS)

    def try_fix(v):
        if not has_mojibake(v):
            return v
        try:
            return str(v).encode("latin1").decode("utf-8")
        except (UnicodeDecodeError, UnicodeEncodeError):
            return v

    n_fixed = int(cleaned[column].apply(has_mojibake).sum())
    cleaned[column] = cleaned[column].apply(try_fix)
    return cleaned, f"Se intentó corregir la codificación de {n_fixed} valor(es) en '{column}' (reinterpretando como UTF-8)."


# Orden de aplicación: texto/codificación primero, valores numéricos después,
# duplicados al final (para que corregir valores no genere ni oculte duplicados
# de forma impredecible según el orden en que el usuario los haya pedido).
FIX_ORDER = [
    "encoding", "currency", "numeric_as_text", "date_format",
    "city_abbrev", "category_consistency", "negatives", "outliers", "nulls", "duplicates",
]

FIXERS = {
    "encoding": fix_encoding,
    "currency": fix_currency,
    "numeric_as_text": fix_numeric_as_text,
    "date_format": fix_date_format,
    "city_abbrev": fix_city_abbrev,
    "category_consistency": fix_category_consistency,
    "negatives": fix_negatives,
    "outliers": fix_outliers,
    "nulls": fix_nulls,
    "duplicates": fix_duplicates,
}

# Hallazgos que representan un conflicto de criterio de negocio, sin un arreglo
# automático seguro (ver docstring del módulo).
NOT_AUTO_FIXABLE = {"price_consistency", "code_consistency"}


def apply_fixes(df: pd.DataFrame, findings: list[dict], rule_ids: list[str] | None = None) -> tuple[pd.DataFrame, list[dict], list[str]]:
    """
    Aplica, en el orden fijo de FIX_ORDER, los hallazgos de `findings` cuyo
    rule_id tiene un fixer y (si se pasó `rule_ids`) está en esa lista.
    Devuelve (df_limpio, mensajes_aplicados, hallazgos_sin_arreglo_automático).
    """
    applicable = [
        f for f in findings
        if f["rule_id"] in FIXERS and (rule_ids is None or f["rule_id"] in rule_ids)
    ]
    applicable.sort(key=lambda f: FIX_ORDER.index(f["rule_id"]) if f["rule_id"] in FIX_ORDER else len(FIX_ORDER))

    cleaned = df.copy()
    applied: list[dict] = []
    for f in applicable:
        fixer = FIXERS[f["rule_id"]]
        if f["rule_id"] == "duplicates":
            cleaned, msg = fixer(cleaned)
            applied.append({"rule_id": f["rule_id"], "rule_name": f["rule_name"], "column": None, "message": msg})
            continue
        for col in f["columns"]:
            if col not in cleaned.columns:
                continue
            cleaned, msg = fixer(cleaned, col)
            applied.append({"rule_id": f["rule_id"], "rule_name": f["rule_name"], "column": col, "message": msg})

    not_fixable = [f["rule_name"] for f in findings if f["rule_id"] in NOT_AUTO_FIXABLE]
    return cleaned, applied, not_fixable
