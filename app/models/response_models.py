from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class QueryResult:
    rows: list[dict] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    query_duration_ms: int | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class AgentResponse:
    answer: str
    interpretation: dict = field(default_factory=dict)
    sql: str | None = None
    status: str = "success"
    rows: list[dict] = field(default_factory=list)

