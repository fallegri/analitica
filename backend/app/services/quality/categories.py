import difflib

from app.services.quality.base import QualityFinding


def check_category_consistency(df, col, series, profile) -> QualityFinding | None:
    if profile.inferred_type != "categórico":
        return None
    uniques = series.dropna().astype(str).str.strip().unique().tolist()
    if len(uniques) < 2:
        return None

    flagged: list[tuple[str, str]] = []
    for i, a in enumerate(uniques):
        for b in uniques[i + 1:]:
            if a == b:
                continue
            if a.lower() == b.lower():
                flagged.append((a, b))
            elif difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio() > 0.85:
                flagged.append((a, b))

    if not flagged:
        return None
    detail = "; ".join(f"'{a}' vs '{b}'" for a, b in flagged[:5])
    return QualityFinding(
        rule_id="category_consistency",
        rule_name="Categorías con nombres inconsistentes",
        severity="baja",
        columns=[col],
        count=len(flagged),
        detail=f"Posibles variantes del mismo valor en '{col}': {detail}.",
        examples=[a for a, _ in flagged[:5]],
    )
