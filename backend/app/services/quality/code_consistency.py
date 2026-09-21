from app.services.quality.base import QualityFinding
from app.services.quality.common import CODE_HINTS, PRODUCT_HINTS, find_col


def check_code_consistency(df, dictionary_entries) -> QualityFinding | None:
    code_col = find_col(df.columns, CODE_HINTS)
    desc_col = find_col(df.columns, PRODUCT_HINTS)
    if not code_col or not desc_col or code_col == desc_col:
        return None

    tmp = df[[code_col, desc_col]].dropna()
    if tmp.empty:
        return None

    grouped = tmp.groupby(code_col)[desc_col].nunique()
    inconsistent = grouped[grouped > 1]
    if inconsistent.empty:
        return None
    return QualityFinding(
        rule_id="code_consistency",
        rule_name="Códigos inconsistentes",
        severity="media",
        columns=[code_col, desc_col],
        count=int(len(inconsistent)),
        detail=f"{len(inconsistent)} código(s) en '{code_col}' están asociados a más de una descripción distinta en '{desc_col}'.",
        examples=inconsistent.index.tolist()[:5],
    )
