from __future__ import annotations

import re

from app.catalog.metric_registry import load_metrics
from app.config import settings
from app.models.query_models import QueryPlan, ValidationResult


BLOCKED_KEYWORDS = {
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "create",
    "truncate",
    "merge",
    "copy",
    "put",
    "get",
    "call",
}


class SQLValidator:
    def validate(self, plan: QueryPlan) -> ValidationResult:
        if not plan.sql:
            return ValidationResult(False, "No SQL was generated.")
        sql = plan.sql.strip()
        lowered = sql.lower()
        if not (lowered.startswith("select") or lowered.startswith("with")):
            return ValidationResult(False, "Only SELECT statements are allowed.")
        if any(re.search(rf"\b{keyword}\b", lowered) for keyword in BLOCKED_KEYWORDS):
            return ValidationResult(False, "The query contains a blocked SQL operation.")
        if ";" in sql.rstrip(";"):
            return ValidationResult(False, "Only one SQL statement is allowed.")
        if re.search(r"select\s+\*", lowered):
            return ValidationResult(False, "Wildcard column selection is not allowed.")
        if settings.snowflake_database.lower() not in lowered:
            return ValidationResult(False, "The query does not use the approved database.")

        metric = load_metrics()[plan.metric.metric_id]
        if plan.query_type == "age_breakdown":
            required_identifiers = [
                "2020_CBG_B01",
                metric.geography_column,
                "B01001e3",
                "B01001e27",
                "B01001e49",
            ]
        elif plan.query_type == "race_breakdown":
            required_identifiers = [
                "2020_CBG_B02",
                metric.geography_column,
                "B02001e2",
                "B02001e8",
            ]
        else:
            required_identifiers = [metric.table, metric.geography_column, *(metric.source_columns or metric.estimate_columns)]
            if metric.estimate_column:
                required_identifiers.append(metric.estimate_column)
        for identifier in required_identifiers:
            if not identifier:
                continue
            if identifier.lower() not in lowered:
                return ValidationResult(False, f"The query is missing approved identifier {identifier}.")
        return ValidationResult(True)
