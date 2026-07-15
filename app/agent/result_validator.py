from __future__ import annotations

from app.models.query_models import QueryPlan, ValidationResult
from app.models.response_models import QueryResult


class ResultValidator:
    def validate(self, plan: QueryPlan, result: QueryResult) -> ValidationResult:
        if result.error:
            return ValidationResult(False, result.error)
        if not result.rows:
            return ValidationResult(False, "The query returned no rows.")
        if plan.query_type == "age_breakdown":
            if not any(key.lower().startswith("age_") or key.lower() == "under_5" for key in result.rows[0]):
                return ValidationResult(False, "The age breakdown query did not return age-band columns.")
            return ValidationResult(True)
        if plan.query_type == "race_breakdown":
            if not any("race" in key.lower() or "white" in key.lower() for key in result.rows[0]):
                return ValidationResult(False, "The race breakdown query did not return race category columns.")
            return ValidationResult(True)
        for row in result.rows:
            value = row.get("VALUE") if "VALUE" in row else row.get("value")
            if value is None:
                return ValidationResult(False, "The dataset did not contain a usable value for that selection.")
            if isinstance(value, (int, float)) and value < 0:
                return ValidationResult(False, "The query returned an implausible negative value.")
            if plan.metric.metric_id == "total_population" and plan.query_type == "aggregate_metric":
                if isinstance(value, (int, float)) and not (1_000 <= value <= 100_000_000):
                    return ValidationResult(False, "The population result failed a broad sanity check.")
        return ValidationResult(True)
