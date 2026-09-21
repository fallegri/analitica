from typing import Any, Optional
from pydantic import BaseModel


class ColumnDictionaryEntry(BaseModel):
    original_header: str
    suggested_name: str
    description: str
    inferred_type: str
    non_null_count: int
    null_count: int
    null_pct: float
    unique_count: int
    sample_values: list[Any]
    min_value: Optional[Any] = None
    max_value: Optional[Any] = None


class QualityFindingOut(BaseModel):
    rule_id: str
    rule_name: str
    severity: str
    columns: list[str]
    count: int
    detail: str
    examples: list[Any] = []


class NumericStatsOut(BaseModel):
    column: str
    mean: float
    median: float
    std: float
    min: float
    q1: float
    q3: float
    max: float


class CategoryFrequencyOut(BaseModel):
    column: str
    top_values: list[Any]  # lista de (valor, cantidad, porcentaje)


class CorrelationOut(BaseModel):
    column_a: str
    column_b: str
    correlation: float
    strength: str


class TableInsightsOut(BaseModel):
    numeric_stats: list[NumericStatsOut] = []
    category_frequencies: list[CategoryFrequencyOut] = []
    correlations: list[CorrelationOut] = []
    suggested_analyses: list[str] = []
    ai_narrative: Optional[str] = None


class TableResult(BaseModel):
    sheet_name: str
    table_index: int
    start_row: int
    end_row: int
    row_count: int
    column_count: int
    dictionary: list[ColumnDictionaryEntry]
    quality_findings: list[QualityFindingOut] = []
    insights: Optional[TableInsightsOut] = None


class ProcessLogEntry(BaseModel):
    step: str
    message: str


class SchemaTableOut(BaseModel):
    table_label: str
    role: str
    key_columns: list[str]


class SchemaRelationshipOut(BaseModel):
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    overlap_ratio: float
    confidence: str


class SchemaDetectionOut(BaseModel):
    shape: str
    tables: list[SchemaTableOut]
    relationships: list[SchemaRelationshipOut]


class AnalyzeResponse(BaseModel):
    filename: str
    process_log: list[ProcessLogEntry]
    tables: list[TableResult]
    schema_detection: Optional[SchemaDetectionOut] = None
    analysis_id: Optional[str] = None
