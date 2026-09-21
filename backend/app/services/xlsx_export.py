"""Exportar DataFrames a bytes de un .xlsx en memoria, sin tocar disco."""
import io

import pandas as pd


def dataframes_to_xlsx_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            safe_name = str(sheet_name)[:31]  # límite de Excel para nombres de hoja
            df.to_excel(writer, sheet_name=safe_name, index=False)
    return buffer.getvalue()
