from __future__ import annotations

from dataclasses import dataclass, field

from app.models.intent_models import Geography


@dataclass
class ConversationState:
    session_id: str
    last_metric: str | None = None
    last_geographies: list[Geography] = field(default_factory=list)
    last_year: int | None = None
    last_query_type: str | None = None
    last_geography_level: str | None = None
    last_geography_scope: str | None = None
    last_operation_type: str | None = None
    last_sort_direction: str | None = None
    last_limit: int | None = None
    mentioned_geographies: list[Geography] = field(default_factory=list)
    last_result_set: list[dict] = field(default_factory=list)

    def remember(
        self,
        metric: str | None,
        geographies: list[Geography],
        year: int | None,
        query_type: str,
        geography_level: str | None = None,
        geography_scope: str | None = None,
        operation_type: str | None = None,
        sort_direction: str | None = None,
        limit: int | None = None,
        result_rows: list[dict] | None = None,
    ) -> None:
        if metric:
            self.last_metric = metric
        if geographies:
            self.last_geographies = geographies
            for geography in geographies:
                if geography.name and all(existing.name != geography.name for existing in self.mentioned_geographies):
                    self.mentioned_geographies.append(geography)
        if year:
            self.last_year = year
        self.last_query_type = query_type
        if geography_level:
            self.last_geography_level = geography_level
        if geography_scope:
            self.last_geography_scope = geography_scope
        if operation_type:
            self.last_operation_type = operation_type
        if sort_direction:
            self.last_sort_direction = sort_direction
        if limit:
            self.last_limit = limit
        if result_rows is not None:
            self.last_result_set = result_rows
