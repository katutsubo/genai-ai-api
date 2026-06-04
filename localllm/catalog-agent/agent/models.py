from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import pandas as pd


@dataclass
class ParsedData:
    file_path: str
    file_type: str  # "csv"
    df: pd.DataFrame
    encoding: str  # e.g. "utf-8", "shift_jis"


@dataclass
class CheckResult:
    rule_id: str
    rule_name: str
    severity: Literal["error", "warning", "info"]
    passed: bool
    message: str
    location: str  # e.g. "column:area_code" or "row:42,col:survey_date"


@dataclass
class ColumnMetadata:
    name: str
    description_ja: str
    description_en: str
    data_type: str  # pandas dtype string
    is_nullable: bool
    is_primary_key: bool
    is_foreign_key: bool
    foreign_key_ref: str | None
    tags: list[str]


@dataclass
class TableMetadata:
    table_name: str
    description_ja: str
    description_en: str
    domain: str  # e.g. "government.statistics"
    owner: str
    tags: list[str]
    columns: list[ColumnMetadata]


@dataclass
class CatalogOutputs:
    catalog_md: Path
    datahub_jsonld: Path
    openmetadata_yaml: Path
    semantic_view_sql: Path
    materialized_view_sql: Path


@dataclass
class LLMResponse:
    content: str
    model: str


@dataclass
class ComparisonResult:
    question: str
    sql_before: str
    sql_after: str
    result_before: list[dict]
    result_after: list[dict]
    score_before: dict  # {"correctness": int, "readability": int, "issues": list[str]}
    score_after: dict
    verdict: Literal["improved", "same", "degraded"]


@dataclass
class AgentResult:
    file_info: dict  # {"file_path", "file_type", "processed_at", "encoding"}
    check_results: list[CheckResult] = field(default_factory=list)
    catalog_outputs: dict = field(default_factory=dict)  # {table_name: CatalogOutputs}
    textsql_comparison: list[ComparisonResult] = field(default_factory=list)
