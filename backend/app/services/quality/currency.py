import re

from app.services.quality.base import QualityFinding

_CURRENCY_SYMBOLS = re.compile(r"(Bs\.?|US\$|USD|\$|€|Gs\.?)", re.IGNORECASE)


def check_currency_consistency(df, col, series, profile) -> QualityFinding | None:
    if profile.inferred_type not in ("texto", "numérico expresado como texto"):
        return None
    values = series.dropna().astype(str)
    found = values.apply(lambda v: (m.group(0) if (m := _CURRENCY_SYMBOLS.search(v)) else None))
    symbols = sorted(set(found.dropna().unique().tolist()))
    if len(symbols) <= 1:
        return None
    return QualityFinding(
        rule_id="currency",
        rule_name="Codificación de moneda inconsistente",
        severity="media",
        columns=[col],
        count=int(found.dropna().shape[0]),
        detail=f"Se detectaron múltiples símbolos/códigos de moneda en '{col}': {', '.join(symbols)}.",
        examples=symbols,
    )
