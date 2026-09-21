from app.services.quality.base import QualityFinding

_CITY_MAP = {
    "scz": "santa cruz", "santa cruz": "santa cruz", "santa cruz de la sierra": "santa cruz",
    "lp": "la paz", "la paz": "la paz",
    "cbb": "cochabamba", "cochabamba": "cochabamba",
    "sre": "sucre", "chuquisaca": "sucre", "sucre": "sucre",
    "oru": "oruro", "oruro": "oruro",
    "tja": "tarija", "tarija": "tarija",
    "pot": "potosi", "potosi": "potosi", "potosí": "potosi",
    "ben": "beni", "beni": "beni",
    "pnd": "pando", "pando": "pando",
}
_NAME_HINTS = ["ciud", "cliud", "city", "depto", "departamento"]


def check_city_abbreviations(df, col, series, profile) -> QualityFinding | None:
    if profile.inferred_type not in ("texto", "categórico"):
        return None
    if not any(h in col.lower() for h in _NAME_HINTS):
        return None

    values = series.dropna().astype(str).str.strip()
    normalized_map: dict[str, set[str]] = {}
    for raw in values:
        norm = _CITY_MAP.get(raw.lower())
        if norm:
            normalized_map.setdefault(norm, set()).add(raw)

    inconsistent = {k: v for k, v in normalized_map.items() if len(v) > 1}
    if not inconsistent:
        return None

    detail_parts = [f"{k} ({'/'.join(sorted(v))})" for k, v in inconsistent.items()]
    return QualityFinding(
        rule_id="city_abbrev",
        rule_name="Abreviaturas de ciudad sin uniformar",
        severity="baja",
        columns=[col],
        count=sum(len(v) for v in inconsistent.values()),
        detail=f"Variantes sin uniformar en '{col}': {'; '.join(detail_parts)}.",
        examples=[x for v in inconsistent.values() for x in v][:5],
    )
