from app.services.quality.base import QualityFinding


def check_nulls(df, col, series, profile) -> QualityFinding | None:
    if profile.null_count == 0:
        return None
    severity = "alta" if profile.null_pct > 30 else ("media" if profile.null_pct > 5 else "baja")
    return QualityFinding(
        rule_id="nulls",
        rule_name="Datos nulos",
        severity=severity,
        columns=[col],
        count=profile.null_count,
        detail=f"{profile.null_count} valores nulos ({profile.null_pct}%) en '{col}'.",
    )
