from __future__ import annotations

from app.catalog.metric_registry import load_metrics
from app.models.intent_models import QueryIntent
from app.models.query_models import QueryPlan, ValidationResult


class QueryPlanner:
    def create_plan(self, intent: QueryIntent) -> tuple[QueryPlan | None, ValidationResult]:
        if intent.needs_clarification:
            return None, ValidationResult(False, intent.clarification_question)
        if not intent.metric or intent.metric not in load_metrics():
            return None, ValidationResult(False, "I could not map that question to a verified Census metric.")

        metric = load_metrics()[intent.metric]
        if intent.year and intent.year > metric.year:
            return None, ValidationResult(
                False,
                f"The available dataset contains historical Census estimates through {metric.year}, not a verified {intent.year} forecast. "
                "I can show the latest available ranking or compare historical years if multiple years are available.",
            )
        if not metric.verified:
            return None, ValidationResult(False, "The matching metric has not been verified yet.")
        if metric.aggregation_behavior == "non_additive" and metric.measure_type != "median" and intent.intent in {"aggregate_metric", "comparison", "ranking", "filter"}:
            return None, ValidationResult(
                False,
                f"{metric.display_name} is not additive, so I will not sum block-group values into a state result.",
            )

        if intent.intent == "ranking":
            if intent.geography_level != "state":
                return None, ValidationResult(False, "This implementation currently supports state-level rankings.")
            row_limit = intent.rank or intent.limit or 1
            plan = QueryPlan(
                query_type="ranking",
                metric=metric,
                geography_filters=[],
                geography_level=intent.geography_level,
                geography_scope="all",
                operation_type=intent.operation_type or "maximum",
                sort_direction=intent.sort_direction or "descending",
                result_rank=intent.rank,
                dimension=intent.dimension or metric.dimension,
                group_by=["state_fips"],
                order_by=[f"value {'ASC' if intent.sort_direction == 'ascending' else 'DESC'}"],
                row_limit=row_limit,
                interpretation=f"Rank states by {metric.display_name.lower()} in {metric.year}",
                llm_attempted=intent.llm_attempted,
                llm_succeeded=intent.llm_succeeded,
                llm_provider=intent.llm_provider,
            )
            return plan, ValidationResult(True)

        if intent.intent == "filter":
            if intent.geography_level not in {"state", "county"}:
                return None, ValidationResult(False, "This implementation currently supports state- and county-level filters.")
            if not intent.threshold_operator or intent.threshold_value is None:
                return None, ValidationResult(False, "I need a threshold such as more than 10 million people.")
            parent_filters = []
            if intent.geography_level == "county":
                parent_filters = [
                    {
                        "type": geo.type,
                        "name": geo.name,
                        "fips": geo.fips_code,
                        "county_fips": geo.county_fips,
                        "filter_column": metric.geography_column,
                        "filter_method": "prefix",
                        "prefix_length": 2,
                    }
                    for geo in intent.geographies
                    if geo.type == "state" and geo.fips_code
                ]
                if not parent_filters:
                    return None, ValidationResult(False, "Which state should I search counties within?")
            plan = QueryPlan(
                query_type="filter",
                metric=metric,
                geography_filters=parent_filters,
                geography_level=intent.geography_level,
                geography_scope="within_parent" if parent_filters else "all",
                operation_type="threshold",
                dimension=intent.dimension or metric.dimension,
                threshold_operator=intent.threshold_operator,
                threshold_value=intent.threshold_value,
                group_by=["county_fips" if intent.geography_level == "county" else "state_fips"],
                order_by=["value DESC"],
                row_limit=100,
                interpretation=f"{intent.geography_level.title()}s where {metric.display_name.lower()} is {intent.threshold_operator} {intent.threshold_value:,.0f}",
                llm_attempted=intent.llm_attempted,
                llm_succeeded=intent.llm_succeeded,
                llm_provider=intent.llm_provider,
            )
            return plan, ValidationResult(True)

        if not intent.geographies:
            return None, ValidationResult(False, "I need a supported geography before I can query the data.")

        filters = [
            {
                "type": geo.type,
                "name": geo.name,
                "fips": geo.fips_code,
                "county_fips": geo.county_fips,
                "filter_column": metric.geography_column,
                "filter_method": "county_set" if geo.type == "city" and geo.county_fips else "prefix",
                "prefix_length": 5 if geo.type == "city" else 2,
            }
            for geo in intent.geographies
            if (geo.type == "state" and geo.fips_code) or (geo.type == "city" and geo.county_fips)
        ]
        if not filters:
            return None, ValidationResult(False, "Only state-level and verified city county-set questions are supported in this implementation.")

        if intent.intent == "breakdown" and intent.dimension in {"age", "race"}:
            plan = QueryPlan(
                query_type=f"{intent.dimension}_breakdown",
                metric=metric,
                geography_filters=filters,
                geography_level=filters[0]["type"],
                geography_scope="selected",
                operation_type="breakdown",
                dimension=intent.dimension,
                interpretation=f"{intent.dimension.title()} breakdown for {filters[0]['name']} in {metric.year}",
                llm_attempted=intent.llm_attempted,
                llm_succeeded=intent.llm_succeeded,
                llm_provider=intent.llm_provider,
            )
            return plan, ValidationResult(True)

        query_type = "comparison" if intent.intent == "comparison" and len(filters) > 1 else "aggregate_metric"
        names = ", ".join(item["name"] for item in filters)
        plan = QueryPlan(
            query_type=query_type,
            metric=metric,
            geography_filters=filters,
            geography_level=intent.geography_level or "state",
            geography_scope="selected",
            operation_type=intent.operation_type or ("comparison" if query_type == "comparison" else "aggregate"),
            dimension=intent.dimension or metric.dimension,
            interpretation=f"{metric.year} {metric.display_name.lower()} for {names}",
            llm_attempted=intent.llm_attempted,
            llm_succeeded=intent.llm_succeeded,
            llm_provider=intent.llm_provider,
        )
        return plan, ValidationResult(True)
