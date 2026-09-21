import pandas as pd

from app.services.quality.base import QualityFinding


def check_negatives(df, col, series, profile) -> QualityFinding | None:
    if profile.inferred_type != "numérico":
        return None
    numeric = pd.to_numeric(series, errors="coerce")
    negs = numeric[numeric < 0]
    if negs.empty:
        return None
    return QualityFinding(
        rule_id="negatives",
        rule_name="Valores negativos",
        severity="media",
        columns=[col],
        count=int(len(negs)),
        detail=f"{len(negs)} valor(es) negativo(s) en '{col}'.",
        examples=negs.unique().tolist()[:3],
    )
