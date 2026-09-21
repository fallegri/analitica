"""
Detección heurística de relaciones tipo estrella/copo de nieve entre las
tablas detectadas en un mismo archivo. Es intencionalmente una sugerencia,
no una decisión automática (ver conversación con el usuario): el resultado
se muestra para que la persona confirme o descarte cada relación antes de
usarla para enlazar los datos, siguiendo el principio de control del
usuario (ISO 9241).

Heurística:
1. Clasificar cada tabla como "dimensión" (pocas columnas tipo clave, el
   resto descriptivo) o "hecho" (varias columnas tipo clave/referencia +
   medidas numéricas).
2. Buscar relaciones entre tablas: columnas con el mismo nombre normalizado
   y un solapamiento de valores significativo entre ambas tablas.
3. Si alguna relación conecta dos dimensiones entre sí, se sugiere copo de
   nieve; si todas las relaciones son hecho-dimensión, se sugiere estrella.
"""
from dataclasses import dataclass, field
import re

import pandas as pd

from app.services.key_detection import is_key_like


@dataclass
class TableClassification:
    table_label: str
    role: str  # "dimension" | "hecho" | "indeterminado"
    key_columns: list[str]


@dataclass
class RelationshipCandidate:
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    overlap_ratio: float
    confidence: str  # "alta" | "media" | "baja"


@dataclass
class SchemaDetectionResult:
    tables: list[TableClassification]
    relationships: list[RelationshipCandidate]
    shape: str  # "estrella" | "copo_de_nieve" | "sin_relaciones_claras"
    narrative: list[str] = field(default_factory=list)


def _normalize_col_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _classify_table(table_label: str, df: pd.DataFrame) -> TableClassification:
    key_cols = [col for col in df.columns if is_key_like(str(col), df[col])]

    n_cols = max(len(df.columns), 1)
    n_keys = len(key_cols)
    if n_keys >= 2 and (n_keys / n_cols) > 0.3:
        role = "hecho"
    elif n_keys >= 1:
        role = "dimension"
    else:
        role = "indeterminado"

    return TableClassification(table_label=table_label, role=role, key_columns=key_cols)


def _find_relationships(
    tables: dict[str, pd.DataFrame],
    classifications: dict[str, TableClassification],
) -> list[RelationshipCandidate]:
    relationships: list[RelationshipCandidate] = []
    table_names = list(tables.keys())

    for t1 in table_names:
        for t2 in table_names:
            if t1 == t2:
                continue
            df1, df2 = tables[t1], tables[t2]
            for col1 in classifications[t1].key_columns:
                norm1 = _normalize_col_name(col1)
                for col2 in df2.columns:
                    if _normalize_col_name(col2) != norm1:
                        continue
                    values1 = set(df1[col1].dropna().astype(str))
                    values2 = set(df2[col2].dropna().astype(str))
                    if not values1 or not values2:
                        continue
                    overlap = len(values1 & values2) / len(values1)
                    if overlap < 0.3:
                        continue
                    confidence = "alta" if overlap > 0.8 else ("media" if overlap > 0.5 else "baja")
                    relationships.append(RelationshipCandidate(
                        from_table=t1, from_column=col1,
                        to_table=t2, to_column=col2,
                        overlap_ratio=round(overlap, 2), confidence=confidence,
                    ))
    return relationships


def _dedupe(relationships: list[RelationshipCandidate]) -> list[RelationshipCandidate]:
    seen = set()
    unique: list[RelationshipCandidate] = []
    for r in relationships:
        sig = tuple(sorted([(r.from_table, r.from_column), (r.to_table, r.to_column)]))
        if sig in seen:
            continue
        seen.add(sig)
        unique.append(r)
    return unique


def detect_schema(tables: dict[str, pd.DataFrame]) -> SchemaDetectionResult:
    narrative: list[str] = []

    if len(tables) < 2:
        narrative.append("Solo se detectó una tabla; no hay suficientes tablas para sugerir relaciones de esquema.")
        return SchemaDetectionResult(tables=[], relationships=[], shape="sin_relaciones_claras", narrative=narrative)

    classifications = {label: _classify_table(label, df) for label, df in tables.items()}
    for label, c in classifications.items():
        narrative.append(
            f"Tabla '{label}' clasificada como {c.role} "
            f"(columnas tipo clave: {', '.join(str(k) for k in c.key_columns) or 'ninguna'})."
        )

    relationships = _dedupe(_find_relationships(tables, classifications))
    for r in relationships:
        narrative.append(
            f"Posible relación: '{r.from_table}.{r.from_column}' ↔ '{r.to_table}.{r.to_column}' "
            f"(solapamiento de valores: {int(r.overlap_ratio * 100)}%, confianza {r.confidence})."
        )

    if not relationships:
        shape = "sin_relaciones_claras"
        narrative.append("No se encontraron relaciones claras entre las tablas con la heurística actual.")
    else:
        dim_to_dim = any(
            classifications[r.from_table].role == "dimension" and classifications[r.to_table].role == "dimension"
            for r in relationships
        )
        shape = "copo_de_nieve" if dim_to_dim else "estrella"
        narrative.append(f"Patrón sugerido: esquema tipo {shape.replace('_', ' ')}. Confirmá o descartá cada relación antes de usarla para enlazar los datos.")

    return SchemaDetectionResult(
        tables=list(classifications.values()),
        relationships=relationships,
        shape=shape,
        narrative=narrative,
    )
