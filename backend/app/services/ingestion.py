"""
Ingesta y detección de tablas.

Responsabilidad única: dado un archivo Excel o CSV, devolver una lista de
bloques crudos (DataFrame + metadatos de ubicación), uno por cada tabla
detectada dentro de cada hoja. No hace perfilado ni diccionario — eso
vive en profiling.py y dictionary.py (separación de responsabilidades).
"""
from dataclasses import dataclass
import io

import pandas as pd


@dataclass
class RawTableBlock:
    sheet_name: str
    table_index: int
    start_row: int  # fila (0-index, relativa a la hoja) donde empieza el encabezado
    end_row: int     # última fila de datos (inclusive)
    df: pd.DataFrame  # ya con encabezados aplicados como columnas


def _split_sheet_into_blocks(raw: pd.DataFrame, sheet_name: str) -> list[RawTableBlock]:
    """
    Recorre una hoja leída SIN encabezado (todo como filas crudas) y la
    parte en bloques cada vez que encuentra una fila completamente vacía
    seguida de contenido. El primer renglón no vacío de cada bloque se
    toma como fila de encabezado.
    """
    blocks: list[RawTableBlock] = []
    n_rows = len(raw)
    row_is_empty = raw.apply(lambda r: r.isna().all(), axis=1)

    segments: list[tuple[int, int]] = []
    seg_start = None
    for i in range(n_rows):
        if not row_is_empty.iloc[i]:
            if seg_start is None:
                seg_start = i
        else:
            if seg_start is not None:
                segments.append((seg_start, i - 1))
                seg_start = None
    if seg_start is not None:
        segments.append((seg_start, n_rows - 1))

    table_index = 0
    for seg_start, seg_end in segments:
        if seg_end - seg_start < 1:
            # un único renglón no forma una tabla utilizable (solo encabezado, sin datos)
            continue
        header_row = raw.iloc[seg_start]
        data = raw.iloc[seg_start + 1: seg_end + 1].copy()
        headers = [
            str(h).strip() if pd.notna(h) else f"columna_sin_nombre_{idx+1}"
            for idx, h in enumerate(header_row)
        ]
        data.columns = headers
        data = data.dropna(axis=1, how="all")
        data = data.reset_index(drop=True)
        blocks.append(
            RawTableBlock(
                sheet_name=sheet_name,
                table_index=table_index,
                start_row=seg_start,
                end_row=seg_end,
                df=data,
            )
        )
        table_index += 1
    return blocks


def load_file(filename: str, content: bytes) -> tuple[list[RawTableBlock], list[str]]:
    """
    Devuelve (bloques_detectados, log_de_proceso).
    El log es una lista de mensajes en texto plano listos para narrar al usuario.
    """
    log: list[str] = []
    blocks: list[RawTableBlock] = []
    lower = filename.lower()

    if lower.endswith(".csv"):
        log.append(f"Se detectó un archivo CSV ('{filename}'). Se leerá como una sola tabla.")
        raw = pd.read_csv(io.BytesIO(content), header=None, dtype=object)
        log.append(f"Se cargaron {len(raw)} filas y {raw.shape[1]} columnas crudas antes de detectar encabezados.")
        sheet_blocks = _split_sheet_into_blocks(raw, sheet_name="CSV")
        log.append(f"Se detectaron {len(sheet_blocks)} tabla(s) dentro del archivo (separadas por filas vacías, si las hubiera).")
        blocks.extend(sheet_blocks)

    elif lower.endswith((".xlsx", ".xls", ".xlsm")):
        xls = pd.ExcelFile(io.BytesIO(content))
        log.append(f"Se detectó un archivo Excel ('{filename}') con {len(xls.sheet_names)} hoja(s): {', '.join(xls.sheet_names)}.")
        for sheet_name in xls.sheet_names:
            raw = xls.parse(sheet_name, header=None, dtype=object)
            if raw.dropna(how="all").empty:
                log.append(f"Hoja '{sheet_name}': está vacía, se omite.")
                continue
            sheet_blocks = _split_sheet_into_blocks(raw, sheet_name=sheet_name)
            log.append(f"Hoja '{sheet_name}': {len(raw)} filas crudas revisadas, se detectaron {len(sheet_blocks)} tabla(s).")
            blocks.extend(sheet_blocks)
    else:
        raise ValueError(f"Formato de archivo no soportado: {filename}. Se admiten .xlsx, .xls, .csv por ahora.")

    total_rows = sum(len(b.df) for b in blocks)
    log.append(f"Ingesta completa: {len(blocks)} tabla(s) en total, {total_rows} filas de datos combinadas.")
    return blocks, log
