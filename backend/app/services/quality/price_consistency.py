import re

import pandas as pd

from app.services.quality.base import QualityFinding
from app.services.quality.common import CODE_HINTS, PRICE_HINTS, PRODUCT_HINTS, find_col


def check_price_consistency(df, dictionary_entries) -> QualityFinding | None:
    key_col = find_col(df.columns, CODE_HINTS) or find_col(df.columns, PRODUCT_HINTS)
    price_col = find_col(df.columns, PRICE_HINTS)
    if not key_col or not price_col or key_col == price_col:
        return None

    cleaned = df[price_col].astype(str).str.replace(r"[^\d.,\-]", "", regex=True).str.replace(",", ".", regex=False)
    prices = pd.to_numeric(cleaned, errors="coerce")
    tmp = pd.DataFrame({"key": df[key_col], "price": prices}).dropna()
    if tmp.empty:
        return None

    grouped = tmp.groupby("key")["price"].nunique()
    inconsistent = grouped[grouped > 1]
    if inconsistent.empty:
        return None
    return QualityFinding(
        rule_id="price_consistency",
        rule_name="Precios inconsistentes",
        severity="media",
        columns=[key_col, price_col],
        count=int(len(inconsistent)),
        detail=f"{len(inconsistent)} valor(es) de '{key_col}' tienen más de un precio distinto en '{price_col}'.",
        examples=inconsistent.index.tolist()[:5],
    )
