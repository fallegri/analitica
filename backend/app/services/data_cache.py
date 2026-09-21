"""
Cache en memoria de los DataFrames crudos de un análisis, para poder
agregarlos bajo demanda (distintas combinaciones de medida/agrupación al
graficar) sin pedir de nuevo el archivo original.

Limitación importante para Vercel: esto vive en memoria del proceso. En
un entorno serverless cada invocación puede correr en un proceso nuevo,
así que no hay garantía de que el cache siga disponible en el siguiente
request. Sirve tal cual para desarrollo local o un servidor long-running;
en serverless, si hace falta graficar después de que la función se
reciclό, la alternativa es volver a analizar el archivo o persistir las
filas crudas en Neon (más pesado, no implementado todavía — ver README).
"""
import pandas as pd

_CACHE: dict[str, dict[str, pd.DataFrame]] = {}  # analysis_id -> {table_label: df}
_MAX_ENTRIES = 20


def store_tables(analysis_id: str, tables: dict[str, pd.DataFrame]) -> None:
    if len(_CACHE) >= _MAX_ENTRIES and analysis_id not in _CACHE:
        oldest = next(iter(_CACHE))
        _CACHE.pop(oldest, None)
    _CACHE[analysis_id] = tables


def get_table(analysis_id: str, table_label: str) -> "pd.DataFrame | None":
    return _CACHE.get(analysis_id, {}).get(table_label)
