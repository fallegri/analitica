from app.services.quality.base import QualityFinding


def check_duplicates(df, dictionary_entries) -> QualityFinding | None:
    dup_mask = df.duplicated(keep=False)
    if not dup_mask.any():
        return None
    return QualityFinding(
        rule_id="duplicates",
        rule_name="Registros duplicados",
        severity="media",
        columns=list(df.columns),
        count=int(dup_mask.sum()),
        detail=f"{int(dup_mask.sum())} fila(s) duplicada(s) completas encontradas en la tabla.",
    )
