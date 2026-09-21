import re

from app.services.quality.base import QualityFinding

_DDMMYYYY = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")


def check_date_format(df, col, series, profile) -> QualityFinding | None:
    if profile.inferred_type != "fecha":
        return None
    values = series.dropna().astype(str).str.strip()
    is_ddmmyyyy = values.apply(lambda v: bool(_DDMMYYYY.match(v)))
    inconsistent = values[~is_ddmmyyyy]
    if inconsistent.empty:
        return None
    return QualityFinding(
        rule_id="date_format",
        rule_name="Formato de fecha inconsistente (esperado dd/mm/yyyy)",
        severity="media",
        columns=[col],
        count=int(len(inconsistent)),
        detail=f"{len(inconsistent)} valor(es) en '{col}' no siguen el formato dd/mm/yyyy.",
        examples=inconsistent.unique().tolist()[:3],
    )
