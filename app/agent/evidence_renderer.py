from __future__ import annotations

import hashlib
import re
from typing import Any

from app.catalog.age_bands import age_range_label, columns_for_age_range
from app.catalog.geography import load_counties, load_states
from app.models.query_models import QueryPlan
from app.models.response_models import QueryResult


CATALOG_VERSION = "verified_metrics:2020-acs-5yr"
DATASET_ID = "acs_5_year_2020"
DATASET_LABEL = "ACS 2020 5-Year"


def metric_label(plan: QueryPlan) -> str:
    if plan.metric.metric_id == "population_by_age" and (plan.age_min is not None or plan.age_max is not None):
        label = age_range_label(plan.age_min, plan.age_max)
        if plan.value_kind == "percentage":
            return f"Percentage of residents {label}"
        return f"Population {label}"
    return plan.metric.display_name


def source_columns(plan: QueryPlan) -> list[str]:
    if plan.metric.metric_id == "population_by_age" and (plan.age_min is not None or plan.age_max is not None):
        columns = columns_for_age_range(plan.age_min, plan.age_max)
        if plan.value_kind == "percentage":
            return [*columns, "B01003e1"]
        return columns
    return plan.metric.source_columns or plan.metric.estimate_columns


def calculation(plan: QueryPlan) -> str:
    if plan.metric.metric_id == "population_by_age" and (plan.age_min is not None or plan.age_max is not None):
        return "dynamic_age_percentage" if plan.value_kind == "percentage" else "dynamic_age_count"
    return plan.metric.calculation


def source_variable(column: str) -> str:
    match = re.match(r"^([A-Za-z]\d+)[eE](\d+)$", column)
    if not match:
        return column
    return f"{match.group(1).upper()}_{int(match.group(2)):03d}E"


def _row_value(row: dict[str, Any]) -> Any:
    return row.get("VALUE") if "VALUE" in row else row.get("value")


def _state_lookup() -> dict[str, str]:
    return {meta["state_fips"]: name for name, meta in load_states().items()}


def _geography_from_row(plan: QueryPlan, row: dict[str, Any]) -> str | None:
    if plan.query_type in {"aggregate_metric", "age_breakdown", "race_breakdown"} and plan.geography_filters:
        return plan.geography_filters[0]["name"]
    if row.get("GEOGRAPHY_NAME") or row.get("geography_name"):
        return row.get("GEOGRAPHY_NAME") or row.get("geography_name")
    state_fips = row.get("STATE_FIPS") or row.get("state_fips")
    county_fips = row.get("COUNTY_FIPS") or row.get("county_fips")
    if county_fips:
        return load_counties().get(str(county_fips), "Unknown county")
    if state_fips:
        return _state_lookup().get(str(state_fips), "Unknown state")
    return None


def _operation_name(plan: QueryPlan) -> str:
    return {
        "ranking": "rank",
        "comparison": "compare",
        "filter": "filter",
        "grouped_metric": "group_by",
        "aggregate_metric": "lookup",
        "age_breakdown": "breakdown",
        "race_breakdown": "breakdown",
    }.get(plan.query_type, plan.query_type)


def _filters(plan: QueryPlan) -> list[dict[str, Any]]:
    filters = []
    for item in plan.geography_filters:
        filters.append(
            {
                "type": item.get("type"),
                "name": item.get("name"),
                "fips": item.get("fips"),
                "county_fips": item.get("county_fips") or None,
                "filter_method": item.get("filter_method"),
            }
        )
    return filters


def operation_contract(plan: QueryPlan) -> dict[str, Any]:
    contract = {
        "operation": _operation_name(plan),
        "metric_id": plan.metric.metric_id,
        "metric_label": metric_label(plan),
        "geography_level": plan.geography_level,
        "filters": _filters(plan),
        "year": plan.metric.year,
    }
    if plan.query_type == "ranking":
        contract["sort"] = {
            "field": "metric_value",
            "direction": "asc" if plan.sort_direction == "ascending" else "desc",
        }
        contract["limit"] = plan.row_limit
        contract["rank"] = plan.result_rank
    if plan.query_type == "filter":
        contract["predicate"] = {
            "field": "metric_value",
            "operator": plan.threshold_operator,
            "value": plan.threshold_value,
        }
    if plan.query_type == "grouped_metric":
        contract["group_by"] = plan.group_by
        contract["limit"] = plan.row_limit
    if plan.query_type == "retail_gap_analysis":
        contract["operation"] = "retail_gap_analysis"
        contract["sort"] = {"field": "avg_distance_from_home_meters", "direction": "desc"}
        contract["limit"] = plan.row_limit
        contract["income_filter"] = {
            "metric_id": plan.analysis_params.get("income_metric_id", "median_household_income"),
            "threshold": plan.analysis_params.get("income_threshold"),
            "percentile": plan.analysis_params.get("income_percentile", 0.8),
        }
        contract["brand_source"] = plan.analysis_params.get("brand_source", "TOP_BRANDS")
    if plan.age_min is not None or plan.age_max is not None:
        contract["dimension_filter"] = {
            "dimension": "age",
            "min": plan.age_min,
            "max": plan.age_max,
            "label": age_range_label(plan.age_min, plan.age_max),
            "value_kind": plan.value_kind or "count",
        }
    return contract


def metric_contract(plan: QueryPlan) -> dict[str, Any]:
    columns = source_columns(plan)
    source_variables = [source_variable(column) for column in columns]
    contract = {
        "id": plan.metric.metric_id,
        "display_name": metric_label(plan),
        "description": plan.metric.description,
        "dataset": DATASET_ID,
        "source_table": plan.metric.table,
        "estimate_expression": {
            "type": calculation(plan),
            "columns": columns,
        },
        "unit": "%" if plan.metric.metric_id == "population_by_age" and plan.value_kind == "percentage" else plan.metric.unit,
        "aggregation": plan.metric.aggregation_behavior,
        "allowed_geography_levels": ["state", "county", "block_group", "verified_city_county_set"],
        "time_coverage": {"start": plan.metric.year, "end": plan.metric.year},
        "universe": plan.metric.universe,
        "synonyms": plan.metric.synonyms,
        "quality_rules": ["value_must_be_nonnegative"],
        "citations": {"dataset": DATASET_LABEL, "variables": source_variables},
    }
    if plan.metric.unit == "USD":
        contract["quality_rules"].append({"value_must_be_less_than": 1_000_000})
    if plan.metric.unit == "%":
        contract["quality_rules"].append({"value_must_be_between": [0, 100]})
    return contract


def claim_payload(plan: QueryPlan, result: QueryResult) -> dict[str, Any]:
    row = result.rows[0] if result.rows else {}
    value = _row_value(row)
    geography = _geography_from_row(plan, row)
    label = metric_label(plan).lower()
    unit = "%" if plan.metric.metric_id == "population_by_age" and plan.value_kind == "percentage" else plan.metric.unit
    claim = None
    if plan.query_type == "retail_gap_analysis":
        value = row.get("AVG_DISTANCE_FROM_HOME_METERS") or row.get("avg_distance_from_home_meters")
        geography = plan.geography_filters[0]["name"] if plan.geography_filters else geography
        claim = (
            f"The listed high-income Census Block Groups in {geography} had the farthest average visitor distance "
            f"from home among analyzed venue CBGs."
        )
        unit = "meters"
    elif plan.query_type == "ranking":
        adjective = "smallest" if plan.sort_direction == "ascending" else "largest"
        claim = f"{geography} had the {adjective} {label} among U.S. states in {plan.metric.year}."
    elif plan.query_type == "aggregate_metric":
        claim = f"{geography} had {label} of {value} {unit} in {plan.metric.year}."
    elif plan.query_type == "comparison":
        claim = f"The response compares {label} for the requested geographies in {plan.metric.year}."
    elif plan.query_type == "filter":
        claim = f"The response lists geographies matching the requested {label} threshold in {plan.metric.year}."
    elif plan.query_type == "grouped_metric":
        claim = f"The response lists {label} grouped by {plan.geography_level} in {plan.metric.year}."
    elif plan.query_type.endswith("_breakdown"):
        claim = f"The response breaks down {geography} by {plan.dimension} in {plan.metric.year}."
    columns = source_columns(plan)
    source_variables = [source_variable(column) for column in columns]
    payload = {
        "claim": claim,
        "value": value,
        "unit": unit,
        "metric_id": plan.metric.metric_id,
        "source_variables": source_variables,
        "dataset": DATASET_LABEL,
        "geography": geography,
        "query_id": result.query_id,
    }
    if len(source_variables) == 1:
        payload["source_variable"] = source_variables[0]
    return payload


def provenance_payload(plan: QueryPlan, result: QueryResult) -> dict[str, Any]:
    sql = plan.sql or ""
    return {
        "query_id": result.query_id,
        "sql_hash": hashlib.sha256(sql.encode("utf-8")).hexdigest()[:16] if sql else None,
        "query_duration_ms": result.query_duration_ms,
        "catalog_version": CATALOG_VERSION,
        "dataset": DATASET_LABEL,
        "dataset_id": DATASET_ID,
        "source_table": plan.metric.table,
        "source_columns": source_columns(plan),
        "source_variables": [source_variable(column) for column in source_columns(plan)],
        "year": plan.metric.year,
    }


def quality_payload(plan: QueryPlan, result: QueryResult) -> dict[str, Any]:
    values = [_row_value(row) for row in result.rows if "VALUE" in row or "value" in row]
    return {
        "status": "verified",
        "row_count": len(result.rows),
        "expected_columns_present": bool(result.columns or result.rows),
        "non_null_metric_values": all(value is not None for value in values),
        "nonnegative_metric_values": all(not isinstance(value, (int, float)) or value >= 0 for value in values),
        "validated_geography_scope": plan.geography_scope,
        "validated_query_type": plan.query_type,
    }


def build_evidence(plan: QueryPlan, result: QueryResult) -> dict[str, Any]:
    return {
        "status": "verified",
        "claim": claim_payload(plan, result),
        "operation": operation_contract(plan),
        "metric_contract": metric_contract(plan),
        "provenance": provenance_payload(plan, result),
        "quality": quality_payload(plan, result),
        "answer_policy": "evidence_bound",
    }
