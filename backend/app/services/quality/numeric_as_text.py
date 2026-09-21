from app.services.quality.base import QualityFinding


def check_numeric_as_text(df, col, series, profile) -> QualityFinding | None:
    if profile.inferred_type != "numérico expresado como texto":
        return None
    return QualityFinding(
        rule_id="numeric_as_text",
        rule_name="Valores numéricos expresados como texto",
        severity="baja",
        columns=[col],
        count=profile.non_null_count,
        detail=f"La columna '{col}' contiene valores numéricos guardados como texto.",
        examples=profile.sample_values[:3],
    )
