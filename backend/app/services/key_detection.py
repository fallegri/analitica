"""
Detección de columnas "tipo clave" (identificadores / posibles claves
foráneas). Los nombres de campo NO se conocen de antemano — dependen del
archivo que suba cada usuario — así que esto nunca debe asumir un nombre
puntual (como "id_venta"). En cambio combina dos señales genéricas:

1. Patrón de nombre: vocabulario común de identificadores en varias
   convenciones/idiomas (id, cod, sku, folio, referencia, clave, key, pk).
   Cubre la INTENCIÓN del nombre, no un nombre exacto.
2. Señal estructural: si los valores son una secuencia entera consecutiva
   (1, 2, 3, 4...) es casi siempre un índice autogenerado, tenga el nombre
   que tenga la columna (incluso "secuencial", "correlativo", o sin ningún
   patrón reconocible).

Ojo: uniqueness alta por sí sola NO alcanza como señal — una columna de
descripciones puede salir 100% única en una tabla chica sin ser una clave
(ver el bug que corregimos en schema_detection antes de este módulo).
Este es el único lugar donde vive este criterio; diccionario, calidad,
esquema e insights lo importan de acá para no repetirlo y no desalinearse.
"""
import re

import pandas as pd

_KEY_NAME_PATTERN = re.compile(
    r"(_id$|^id$|^id_|cod|codigo|código|sku|folio|referencia|^ref$|_ref$|clave|^key$|_key$|^pk$)",
    re.IGNORECASE,
)


def matches_key_name(col_name: str) -> bool:
    return bool(_KEY_NAME_PATTERN.search(str(col_name)))


def is_sequential_index(series: pd.Series) -> bool:
    """True si la columna es una secuencia entera consecutiva (típico índice autogenerado)."""
    numeric = pd.to_numeric(series.dropna(), errors="coerce")
    if len(numeric) < 3 or numeric.isna().any():
        return False
    if not (numeric == numeric.astype(int)).all():
        return False
    sorted_vals = numeric.sort_values().reset_index(drop=True)
    diffs = sorted_vals.diff().dropna()
    return bool((diffs == 1).all())


def is_key_like(col_name: str, series: "pd.Series | None" = None) -> bool:
    if matches_key_name(col_name):
        return True
    if series is not None and is_sequential_index(series):
        return True
    return False
