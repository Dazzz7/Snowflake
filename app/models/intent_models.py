from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Geography:
    type: str = "unknown"
    name: str | None = None
    fips_code: str | None = None
    county_fips: list[str] = field(default_factory=list)
    parent: str | None = None
    aliases: list[str] = field(default_factory=list)


@dataclass
class QueryIntent:
    intent: str = "unsupported"
    metric: str | None = None
    geographies: list[Geography] = field(default_factory=list)
    geography_level: str | None = None
    geography_scope: str | None = None
    year: int | None = None
    aggregation: str | None = None
    operation_type: str | None = None
    sort_direction: str | None = None
    limit: int | None = None
    rank: int | None = None
    threshold_operator: str | None = None
    threshold_value: float | None = None
    dimension: str | None = None
    needs_clarification: bool = False
    clarification_question: str | None = None
    unsupported_reason: str | None = None
    llm_attempted: bool = False
    llm_succeeded: bool = False
    llm_provider: str | None = None
