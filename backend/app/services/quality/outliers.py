import pandas as pd

from app.services.quality.base import QualityFinding


def check_outliers(df, col, series, profile) -> QualityFinding | None:
    if profile.inferred_type != "numérico":
        return None
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if len(numeric) < 5:
        return None
    q1, q3 = numeric.quantile(0.25), numeric.quantile(0.75)
    iqr = q3 - q1
    if iqr == 0:
        return None
    lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    outliers = numeric[(numeric < lower) | (numeric > upper)]
    if outliers.empty:
        return None
    return QualityFinding(
        rule_id="outliers",
        rule_name="Valores atípicos",
        severity="media",
        columns=[col],
        count=int(len(outliers)),
        detail=f"{len(outliers)} valor(es) atípico(s) en '{col}' (fuera de [{lower:.2f}, {upper:.2f}]).",
        examples=outliers.unique().tolist()[:3],
    )
