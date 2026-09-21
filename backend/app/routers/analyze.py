from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Query

from app.models.schemas import (
    AnalyzeResponse,
    CategoryFrequencyOut,
    CorrelationOut,
    NumericStatsOut,
    ProcessLogEntry,
    QualityFindingOut,
    SchemaDetectionOut,
    SchemaRelationshipOut,
    SchemaTableOut,
    TableInsightsOut,
    TableResult,
)
from app.routers.auth_deps import require_min_rank
from app.services.ai_providers import generate_text, load_config
from app.services.data_cache import store_tables
from app.services.dictionary import build_dictionary_entry
from app.services.history import save_analysis
from app.services.ingestion import load_file
from app.services.insights import compute_table_insights, generate_ai_narrative
from app.services.profiling import profile_column
from app.services.quality.engine import run_quality_checks
from app.services.schema_detection import detect_schema

router = APIRouter()

_SEVERITY_ORDER = {"alta": 0, "media": 1, "baja": 2}


async def run_analysis(filename: str, content: bytes, use_ai: bool) -> AnalyzeResponse:
    """
    Lógica completa de análisis (ingesta → diccionario → calidad → insights →
    esquema → historial), independiente de cómo llegaron los bytes del
    archivo. La comparte el endpoint de subida normal y el generador de
    datos sintéticos, para no duplicar todo este pipeline en dos lugares.
    """
    process_log: list[ProcessLogEntry] = []

    try:
        blocks, ingestion_log = load_file(filename, content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    process_log.append(ProcessLogEntry(step="Ingesta", message=f"Archivo recibido: {filename}."))
    for msg in ingestion_log:
        process_log.append(ProcessLogEntry(step="Ingesta", message=msg))

    if not blocks:
        process_log.append(ProcessLogEntry(step="Ingesta", message="No se encontraron tablas utilizables en el archivo."))
        return AnalyzeResponse(filename=filename, process_log=process_log, tables=[])

    ai_config = await load_config()
    if use_ai and ai_config.provider != "none":
        process_log.append(ProcessLogEntry(
            step="IA",
            message=f"Se usará el proveedor '{ai_config.provider}' para mejorar las descripciones del diccionario.",
        ))
    elif use_ai:
        process_log.append(ProcessLogEntry(
            step="IA",
            message="Se pidió usar IA pero no hay proveedor configurado; se continúa solo con reglas heurísticas.",
        ))

    tables: list[TableResult] = []
    tables_for_schema: dict[str, object] = {}
    for block in blocks:
        table_label = f"{block.sheet_name} (tabla {block.table_index + 1})"
        tables_for_schema[table_label] = block.df
        process_log.append(ProcessLogEntry(
            step="Diccionario de datos",
            message=f"Analizando {table_label}: {block.df.shape[0]} filas, {block.df.shape[1]} columnas.",
        ))

        profiles_by_column = {col: profile_column(block.df[col]) for col in block.df.columns}
        entries = []
        for col in block.df.columns:
            entry = build_dictionary_entry(col, profiles_by_column[col])

            if use_ai and ai_config.provider != "none":
                prompt = (
                    "Redactá en español, en una sola oración breve, una descripción de negocio "
                    f"para una columna de datos llamada '{col}' (nombre sugerido: '{entry.suggested_name}'), "
                    f"de tipo {entry.inferred_type}, con valores de ejemplo: {entry.sample_values[:3]}."
                )
                ai_text = await generate_text(ai_config, prompt)
                if ai_text:
                    entry.description = ai_text
                    process_log.append(ProcessLogEntry(
                        step="IA",
                        message=f"{table_label} · columna '{col}': descripción generada por IA.",
                    ))
                else:
                    process_log.append(ProcessLogEntry(
                        step="IA",
                        message=f"{table_label} · columna '{col}': la IA no respondió, se mantiene la descripción heurística.",
                    ))

            entries.append(entry)
            process_log.append(ProcessLogEntry(
                step="Diccionario de datos",
                message=(
                    f"{table_label} · columna '{col}' → sugerida '{entry.suggested_name}' "
                    f"(tipo: {entry.inferred_type}, nulos: {entry.null_pct}%, únicos: {entry.unique_count})."
                ),
            ))

        process_log.append(ProcessLogEntry(
            step="Diccionario de datos",
            message=f"{table_label}: diccionario de datos completo ({len(entries)} columnas descritas).",
        ))

        process_log.append(ProcessLogEntry(
            step="Calidad de datos",
            message=f"Ejecutando reglas de calidad sobre {table_label}...",
        ))
        raw_findings = run_quality_checks(block.df, entries, profiles_by_column)
        raw_findings.sort(key=lambda f: _SEVERITY_ORDER.get(f.severity, 9))

        if raw_findings:
            for f in raw_findings:
                process_log.append(ProcessLogEntry(
                    step="Calidad de datos",
                    message=f"[{f.severity.upper()}] {f.rule_name} — {f.detail}",
                ))
        else:
            process_log.append(ProcessLogEntry(
                step="Calidad de datos",
                message=f"{table_label}: no se encontraron problemas de calidad con las reglas actuales.",
            ))

        quality_out = [
            QualityFindingOut(
                rule_id=f.rule_id, rule_name=f.rule_name, severity=f.severity,
                columns=f.columns, count=f.count, detail=f.detail, examples=f.examples,
            )
            for f in raw_findings
        ]

        process_log.append(ProcessLogEntry(
            step="Análisis de datos",
            message=f"Calculando estadísticas y sugerencias de análisis para {table_label}...",
        ))
        table_insights = compute_table_insights(block.df, entries, profiles_by_column)

        for s in table_insights.numeric_stats:
            process_log.append(ProcessLogEntry(
                step="Análisis de datos",
                message=f"{table_label} · '{s.column}': media={s.mean}, mediana={s.median}, rango [{s.min}, {s.max}].",
            ))
        for f in table_insights.category_frequencies:
            top_str = ", ".join(f"{v} ({p}%)" for v, c, p in f.top_values[:3])
            process_log.append(ProcessLogEntry(
                step="Análisis de datos",
                message=f"{table_label} · '{f.column}': valores más frecuentes → {top_str}.",
            ))
        for c in table_insights.correlations:
            process_log.append(ProcessLogEntry(
                step="Análisis de datos",
                message=f"{table_label}: correlación {c.strength} entre '{c.column_a}' y '{c.column_b}' (r={c.correlation}).",
            ))
        for sug in table_insights.suggested_analyses:
            process_log.append(ProcessLogEntry(step="Análisis de datos", message=f"Sugerencia: {sug}"))

        ai_narrative = None
        if use_ai and ai_config.provider != "none":
            ai_narrative = await generate_ai_narrative(ai_config, table_label, table_insights)
            if ai_narrative:
                process_log.append(ProcessLogEntry(
                    step="IA",
                    message=f"{table_label}: narrativa de análisis generada por IA.",
                ))
            else:
                process_log.append(ProcessLogEntry(
                    step="IA",
                    message=f"{table_label}: la IA no respondió para la narrativa de análisis; queda solo la heurística.",
                ))

        insights_out = TableInsightsOut(
            numeric_stats=[NumericStatsOut(**vars(s)) for s in table_insights.numeric_stats],
            category_frequencies=[CategoryFrequencyOut(column=f.column, top_values=f.top_values) for f in table_insights.category_frequencies],
            correlations=[CorrelationOut(**vars(c)) for c in table_insights.correlations],
            suggested_analyses=table_insights.suggested_analyses,
            ai_narrative=ai_narrative,
        )

        tables.append(TableResult(
            sheet_name=block.sheet_name,
            table_index=block.table_index,
            start_row=block.start_row,
            end_row=block.end_row,
            row_count=block.df.shape[0],
            column_count=block.df.shape[1],
            dictionary=entries,
            quality_findings=quality_out,
            insights=insights_out,
        ))

    process_log.append(ProcessLogEntry(
        step="Resumen",
        message=f"Análisis finalizado: {len(tables)} tabla(s) procesada(s), "
                f"{sum(len(t.quality_findings) for t in tables)} hallazgo(s) de calidad en total.",
    ))

    schema_out = None
    if len(tables_for_schema) >= 2:
        process_log.append(ProcessLogEntry(
            step="Esquema",
            message=f"Analizando posibles relaciones entre las {len(tables_for_schema)} tablas detectadas...",
        ))
        result = detect_schema(tables_for_schema)
        for msg in result.narrative:
            process_log.append(ProcessLogEntry(step="Esquema", message=msg))
        schema_out = SchemaDetectionOut(
            shape=result.shape,
            tables=[SchemaTableOut(table_label=t.table_label, role=t.role, key_columns=[str(k) for k in t.key_columns]) for t in result.tables],
            relationships=[
                SchemaRelationshipOut(
                    from_table=r.from_table, from_column=str(r.from_column),
                    to_table=r.to_table, to_column=str(r.to_column),
                    overlap_ratio=r.overlap_ratio, confidence=r.confidence,
                )
                for r in result.relationships
            ],
        )

    response = AnalyzeResponse(filename=filename, process_log=process_log, tables=tables, schema_detection=schema_out)

    findings_count = sum(len(t.quality_findings) for t in tables)
    analysis_id = await save_analysis(
        filename=filename,
        tables_count=len(tables),
        findings_count=findings_count,
        payload=response.model_dump(),
    )
    response.analysis_id = analysis_id
    store_tables(analysis_id, tables_for_schema)
    response.process_log.append(ProcessLogEntry(
        step="Historial",
        message=f"Análisis guardado en el historial con id {analysis_id}.",
    ))

    return response


# Vercel Hobby: ~4.5MB body limit. Ponemos límite conservador.
MAX_FILE_SIZE = 4 * 1024 * 1024  # 4MB


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    file: UploadFile = File(...),
    use_ai: bool = Query(False, description="Si es true, intenta mejorar las descripciones con el proveedor de IA configurado."),
    actor: dict = Depends(require_min_rank("analista")),
) -> AnalyzeResponse:
    # Verificar tamaño antes de leer todo en memoria
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"Archivo demasiado grande ({len(content) / 1024 / 1024:.1f}MB). Límite: {MAX_FILE_SIZE / 1024 / 1024:.0f}MB. "
                   f"Usá un archivo más pequeño o subí de plan en Vercel."
        )
    return await run_analysis(file.filename, content, use_ai)
