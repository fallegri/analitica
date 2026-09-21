"""
Motor de reglas de calidad. Para agregar una regla nueva: escribirla en su
propio módulo (column-level: firma (df, col, series, profile); table-level:
firma (df, dictionary_entries)) y agregarla a una de las dos listas de abajo.
El motor en sí no cambia (Open/Closed).
"""
from app.services.quality import (
    abbreviations,
    categories,
    code_consistency,
    currency,
    dates,
    duplicates,
    encoding,
    negatives,
    nulls,
    numeric_as_text,
    outliers,
    price_consistency,
)
from app.services.quality.base import QualityFinding

COLUMN_RULES = [
    encoding.check_encoding,
    nulls.check_nulls,
    negatives.check_negatives,
    outliers.check_outliers,
    dates.check_date_format,
    currency.check_currency_consistency,
    numeric_as_text.check_numeric_as_text,
    abbreviations.check_city_abbreviations,
    categories.check_category_consistency,
]

TABLE_RULES = [
    duplicates.check_duplicates,
    price_consistency.check_price_consistency,
    code_consistency.check_code_consistency,
]


def run_quality_checks(df, dictionary_entries, profiles_by_column: dict) -> list[QualityFinding]:
    findings: list[QualityFinding] = []

    for entry in dictionary_entries:
        col = entry.original_header
        series = df[col]
        profile = profiles_by_column[col]
        for rule in COLUMN_RULES:
            finding = rule(df, col, series, profile)
            if finding:
                findings.append(finding)

    for rule in TABLE_RULES:
        finding = rule(df, dictionary_entries)
        if finding:
            findings.append(finding)

    return findings
