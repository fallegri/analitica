"""
Estructura común de hallazgos de calidad. Cada regla (column-level o
table-level) devuelve None si no encuentra nada, o un QualityFinding.
Mantener esta interfaz mínima es lo que permite agregar reglas nuevas
sin tocar el motor (Open/Closed).
"""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class QualityFinding:
    rule_id: str
    rule_name: str
    severity: str  # "alta" | "media" | "baja"
    columns: list[str]
    count: int
    detail: str
    examples: list[Any] = field(default_factory=list)
