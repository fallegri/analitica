"""
Generación del diccionario de datos. Responsabilidad única: combinar el
encabezado original + el perfil de la columna (profiling.py) en una
entrada de diccionario con nombre sugerido y descripción legible.

La expansión de abreviaturas es una heurística de reglas (rápida, sin
dependencias externas). Queda como punto de extensión para conectar un
proveedor de IA más adelante, siguiendo el mismo patrón multi-proveedor
usado en PRISM EDA Assistant, sin romper esta interfaz.
"""
import re

from app.models.schemas import ColumnDictionaryEntry
from app.services.profiling import ColumnProfile

_ABBREVIATIONS = {
    "fec": "fecha", "desc": "descripción", "descr": "descripción",
    "cod": "código", "cód": "código", "cant": "cantidad",
    "nro": "número", "num": "número", "n": "número",
    "prov": "proveedor", "cli": "cliente", "dir": "dirección",
    "tel": "teléfono", "obs": "observaciones", "resp": "responsable",
    "fac": "factura", "monto": "monto", "imp": "importe",
    "ciud": "ciudad", "depto": "departamento", "prod": "producto",
    "cat": "categoría", "sucur": "sucursal", "ubic": "ubicación",
    "id": "identificador",
}


def _expand_header(header: str) -> str:
    tokens = re.split(r"[_\-\s]+", header.strip())
    expanded = []
    for tok in tokens:
        key = tok.lower().strip(".")
        expanded.append(_ABBREVIATIONS.get(key, tok))
    return " ".join(expanded).strip()


def _suggest_name(header: str) -> str:
    expanded = _expand_header(header)
    if not expanded:
        return header
    return expanded[0].upper() + expanded[1:] if len(expanded) > 1 else expanded.upper()


def _build_description(suggested_name: str, inferred_type: str, profile) -> str:
    parts = [f"Columna de tipo {inferred_type}."]
    parts.append(f"{profile.non_null_count} valores presentes, {profile.null_count} nulos ({profile.null_pct}%).")
    parts.append(f"{profile.unique_count} valores únicos.")
    if profile.min_value is not None and profile.max_value is not None:
        parts.append(f"Rango: {profile.min_value} a {profile.max_value}.")
    if profile.sample_values:
        parts.append(f"Ejemplos: {', '.join(str(s) for s in profile.sample_values[:3])}.")
    return " ".join(parts)


def build_dictionary_entry(header: str, profile: ColumnProfile) -> ColumnDictionaryEntry:
    suggested_name = _suggest_name(header)
    description = _build_description(suggested_name, profile.inferred_type, profile)
    return ColumnDictionaryEntry(
        original_header=header,
        suggested_name=suggested_name,
        description=description,
        inferred_type=profile.inferred_type,
        non_null_count=profile.non_null_count,
        null_count=profile.null_count,
        null_pct=profile.null_pct,
        unique_count=profile.unique_count,
        sample_values=profile.sample_values,
        min_value=profile.min_value,
        max_value=profile.max_value,
    )
