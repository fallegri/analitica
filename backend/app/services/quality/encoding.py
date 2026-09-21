from app.services.quality.base import QualityFinding

_MOJIBAKE_MARKERS = ["Ã©", "Ã¡", "Ã­", "Ã³", "Ãº", "Ã±", "Â¿", "Â¡", "â€™", "â€œ", "â€\x9d", "Ã‰", "�"]


def check_encoding(df, col, series, profile) -> QualityFinding | None:
    if profile.inferred_type not in ("texto", "categórico"):
        return None
    values = series.dropna().astype(str)
    hits = values[values.apply(lambda v: any(m in v for m in _MOJIBAKE_MARKERS))]
    if hits.empty:
        return None
    return QualityFinding(
        rule_id="encoding",
        rule_name="Caracteres con codificación errónea",
        severity="alta",
        columns=[col],
        count=int(len(hits)),
        detail=f"{len(hits)} valor(es) con posibles caracteres mal codificados en '{col}'.",
        examples=hits.unique().tolist()[:3],
    )
