from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MetricDefinition:
    metric_id: str
    display_name: str
    description: str
    synonyms: list[str]
    table: str
    geography_column: str
    aggregation: str
    aggregation_behavior: str
    unit: str
    year: int
    universe: str
    verified: bool
    estimate_column: str | None = None
    estimate_columns: list[str] = field(default_factory=list)
    margin_of_error_column: str | None = None
    category: str | None = None
    dimension: str | None = None
    measure_type: str = "count"
    calculation: str = "single_column"
    numerator_columns: list[str] = field(default_factory=list)
    denominator_columns: list[str] = field(default_factory=list)
    source_columns: list[str] = field(default_factory=list)


@dataclass
class QueryPlan:
    query_type: str
    metric: MetricDefinition
    geography_filters: list[dict]
    geography_level: str | None = None
    geography_scope: str | None = None
    operation_type: str | None = None
    sort_direction: str = "descending"
    result_rank: int | None = None
    threshold_operator: str | None = None
    threshold_value: float | None = None
    dimension: str | None = None
    age_min: int | None = None
    age_max: int | None = None
    value_kind: str | None = None
    analysis_params: dict = field(default_factory=dict)
    group_by: list[str] = field(default_factory=list)
    order_by: list[str] = field(default_factory=list)
    row_limit: int | None = None
    interpretation: str = ""
    sql: str | None = None
    parameters: dict = field(default_factory=dict)
    llm_attempted: bool = False
    llm_succeeded: bool = False
    llm_provider: str | None = None


@dataclass
class ValidationResult:
    is_valid: bool
    reason: str | None = None
