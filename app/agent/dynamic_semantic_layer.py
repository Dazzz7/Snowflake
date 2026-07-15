from __future__ import annotations

import re
from typing import Any

from app.agent.hosted_llm_client import HostedLLMClient
from app.catalog.catalog_search import summarize_schema_matches
from app.catalog.geography import find_geographies
from app.config import settings
from app.database.schema_loader import search_columns_metadata
from app.models.query_models import MetricDefinition, QueryPlan, ValidationResult


NUMERIC_TYPES = {"NUMBER", "FLOAT", "DOUBLE", "REAL", "DECIMAL", "INT", "INTEGER"}
ALLOWED_AGGREGATIONS = {"sum", "avg", "approx_median"}
ALLOWED_OPERATIONS = {"ranking", "aggregate_metric", "filter"}
ALLOWED_GEOGRAPHY_LEVELS = {"state", "county"}
ALLOWED_TABLE_PATTERN = re.compile(r"^\d{4}_(CBG|METADATA_CBG|CBG_PATTERNS)", re.IGNORECASE)


def _normal(value: object) -> str:
    return str(value or "").strip()


def _is_numeric(row: dict[str, Any]) -> bool:
    return any(kind in _normal(row.get("DATA_TYPE") or row.get("data_type")).upper() for kind in NUMERIC_TYPES)


def _is_allowed_table(table: str) -> bool:
    return bool(ALLOWED_TABLE_PATTERN.match(table))


def _unit_for_column(column: str, proposed_unit: str) -> str:
    if proposed_unit and proposed_unit.lower() not in {"value", "number", "count"}:
        return proposed_unit
    upper = column.upper()
    if upper == "RAW_VISIT_COUNT":
        return "visits"
    if upper == "RAW_VISITOR_COUNT":
        return "visitors"
    if upper == "DISTANCE_FROM_HOME":
        return "meters"
    if "AMOUNT_LAND" in upper:
        return "square meters"
    return proposed_unit or "value"


def _candidate_key(row: dict[str, Any]) -> tuple[str, str]:
    return (_normal(row.get("TABLE_NAME") or row.get("table_name")).upper(), _normal(row.get("COLUMN_NAME") or row.get("column_name")).upper())


class DynamicSemanticLayer:
    def __init__(self, llm: HostedLLMClient | None = None) -> None:
        self.llm = llm if llm is not None else (HostedLLMClient() if settings.has_hosted_llm_config else None)

    def create_plan(self, question: str) -> tuple[QueryPlan | None, ValidationResult, dict]:
        schema_result = search_columns_metadata(question, limit=30)
        diagnostics = {
            "schema_query_id": schema_result.query_id,
            "schema_error": schema_result.error,
            "schema_matches": summarize_schema_matches(schema_result.rows, limit=12) if not schema_result.error else [],
        }
        if schema_result.error:
            return None, ValidationResult(False, schema_result.error), diagnostics
        candidates = [row for row in schema_result.rows if self._candidate_is_eligible(row)]
        diagnostics["eligible_candidates"] = summarize_schema_matches(candidates, limit=12)
        if not candidates:
            return None, ValidationResult(False, "No eligible numeric Census Block Group columns were found in live metadata."), diagnostics

        contract = self._contract_from_llm(question, candidates) if self.llm else None
        if not contract:
            contract = self._contract_deterministically(question, candidates)
        diagnostics["contract"] = contract

        contract_validation = self._validate_contract(question, contract, candidates)
        if not contract_validation.is_valid:
            return None, contract_validation, diagnostics

        plan = self._plan_from_contract(question, contract)
        diagnostics["validated_contract"] = contract
        return plan, ValidationResult(True), diagnostics

    def _candidate_is_eligible(self, row: dict[str, Any]) -> bool:
        table = _normal(row.get("TABLE_NAME") or row.get("table_name"))
        column = _normal(row.get("COLUMN_NAME") or row.get("column_name"))
        if column.upper() == "CENSUS_BLOCK_GROUP":
            return False
        if not _is_allowed_table(table):
            return False
        return _is_numeric(row)

    def _contract_from_llm(self, question: str, candidates: list[dict[str, Any]]) -> dict | None:
        if not self.llm:
            return None
        candidate_payload = summarize_schema_matches(candidates, limit=20)
        system = (
            "You propose a constrained Census analytics contract from live schema candidates. "
            "Return strict JSON only. Do not write SQL. Choose only a table and column from candidates. "
            "Allowed operations: ranking, aggregate_metric, filter. Allowed geography levels: state, county. "
            "Allowed aggregations: sum, avg, approx_median. Use sum for additive counts, avg for distances/rates/means, "
            "and approx_median only when the user asks for a median-like column. If unclear, set needs_clarification true."
        )
        payload = self.llm.generate_json(
            system,
            (
                f"Question: {question}\n"
                f"Candidates: {candidate_payload}\n"
                "Return keys: needs_clarification, clarification_question, operation, table, value_column, "
                "geography_column, geography_level, aggregation, display_name, unit, sort_direction, limit, "
                "threshold_operator, threshold_value."
            ),
        )
        return payload if isinstance(payload, dict) else None

    def _contract_deterministically(self, question: str, candidates: list[dict[str, Any]]) -> dict:
        lowered = question.lower()
        candidate = candidates[0]
        column = _normal(candidate.get("COLUMN_NAME") or candidate.get("column_name"))
        aggregation = "sum"
        if any(term in lowered for term in ["average", "avg", "mean", "distance", "rate", "percent", "percentage"]):
            aggregation = "avg"
        if "median" in lowered:
            aggregation = "approx_median"
        operation = "aggregate_metric"
        if any(term in lowered for term in ["highest", "lowest", "top", "rank", "most", "least", "fewest"]):
            operation = "ranking"
        if any(term in lowered for term in ["more than", "less than", "over", "under"]) and re.search(r"\d", lowered):
            operation = "filter"
        sort_direction = "ascending" if any(term in lowered for term in ["lowest", "least", "fewest", "smallest"]) else "descending"
        geography_level = "county" if "county" in lowered or "counties" in lowered else "state"
        return {
            "needs_clarification": False,
            "operation": operation,
            "table": _normal(candidate.get("TABLE_NAME") or candidate.get("table_name")),
            "value_column": column,
            "geography_column": "CENSUS_BLOCK_GROUP",
            "geography_level": geography_level,
            "aggregation": aggregation,
            "display_name": column.replace("_", " ").title(),
            "unit": "value",
            "sort_direction": sort_direction,
            "limit": 5 if "top" in lowered else 1,
        }

    def _validate_contract(self, question: str, contract: dict | None, candidates: list[dict[str, Any]]) -> ValidationResult:
        if not contract:
            return ValidationResult(False, "The dynamic semantic layer could not propose a contract.")
        if contract.get("needs_clarification"):
            return ValidationResult(False, contract.get("clarification_question") or "The dynamic metric request is ambiguous.")
        operation = _normal(contract.get("operation"))
        table = _normal(contract.get("table")).upper()
        column = _normal(contract.get("value_column")).upper()
        geography_column = _normal(contract.get("geography_column") or "CENSUS_BLOCK_GROUP").upper()
        geography_level = _normal(contract.get("geography_level")).lower()
        aggregation = _normal(contract.get("aggregation")).lower()
        if operation not in ALLOWED_OPERATIONS:
            return ValidationResult(False, "The dynamic operation is not supported.")
        if geography_level not in ALLOWED_GEOGRAPHY_LEVELS:
            return ValidationResult(False, "The dynamic geography level must be state or county.")
        if aggregation not in ALLOWED_AGGREGATIONS:
            return ValidationResult(False, "The dynamic aggregation must be sum, avg, or approx_median.")
        if geography_column != "CENSUS_BLOCK_GROUP":
            return ValidationResult(False, "The dynamic plan must use CENSUS_BLOCK_GROUP as the geography key.")
        if not _is_allowed_table(table):
            return ValidationResult(False, "The dynamic table is outside the approved public CBG table allowlist.")
        candidate_keys = {_candidate_key(row) for row in candidates}
        if (table, column) not in candidate_keys:
            return ValidationResult(False, "The dynamic metric column was not found in live schema candidates.")
        if operation == "aggregate_metric" and not find_geographies(question):
            return ValidationResult(False, "A selected geography is required for a dynamic lookup.")
        return ValidationResult(True)

    def _plan_from_contract(self, question: str, contract: dict) -> QueryPlan:
        aggregation = _normal(contract.get("aggregation")).lower()
        operation = _normal(contract.get("operation"))
        table = _normal(contract.get("table")).upper()
        column = _normal(contract.get("value_column"))
        geography_level = _normal(contract.get("geography_level")).lower()
        unit = _unit_for_column(column, _normal(contract.get("unit") or "value"))
        contract["unit"] = unit
        measure_type = "median" if aggregation == "approx_median" else ("average" if aggregation == "avg" else "count")
        calculation = {"sum": "single_column", "avg": "avg_column", "approx_median": "single_column"}[aggregation]
        metric = MetricDefinition(
            metric_id=f"dynamic_{table.lower()}_{column.lower()}",
            display_name=_normal(contract.get("display_name")) or column.replace("_", " ").title(),
            description=f"Dynamic metadata-derived metric from {table}.{column}",
            synonyms=[],
            table=table,
            geography_column="CENSUS_BLOCK_GROUP",
            aggregation=aggregation.upper(),
            aggregation_behavior="metadata_verified_dynamic",
            unit=unit,
            year=int(table[:4]) if table[:4].isdigit() else 2020,
            universe="Live Snowflake metadata-derived Census Block Group column",
            verified=True,
            estimate_column=column,
            estimate_columns=[column],
            source_columns=[column],
            measure_type=measure_type,
            calculation=calculation,
        )
        geographies = find_geographies(question)
        filters = [
            {
                "type": geo.type,
                "name": geo.name,
                "fips": geo.fips_code,
                "county_fips": geo.county_fips,
                "filter_column": "CENSUS_BLOCK_GROUP",
                "filter_method": "county_set" if geo.type == "city" and geo.county_fips else "prefix",
                "prefix_length": 5 if geo.type == "city" else 2,
            }
            for geo in geographies
            if (geo.type == "state" and geo.fips_code) or (geo.type == "city" and geo.county_fips)
        ]
        row_limit = int(contract.get("limit") or 1)
        plan = QueryPlan(
            query_type=operation,
            metric=metric,
            geography_filters=filters,
            geography_level=geography_level,
            geography_scope="all" if operation in {"ranking", "filter"} and not filters else "selected",
            operation_type=operation,
            sort_direction=_normal(contract.get("sort_direction") or "descending"),
            threshold_operator=contract.get("threshold_operator"),
            threshold_value=contract.get("threshold_value"),
            row_limit=row_limit,
            interpretation=f"Dynamic schema-derived {operation} over {table}.{column} using {aggregation}.",
            analysis_params={
                "dynamic_contract": contract,
                "semantic_layer": "live_schema_metadata",
            },
        )
        if operation == "ranking":
            plan.group_by = ["state_fips" if geography_level == "state" else "county_fips"]
            plan.order_by = [f"value {'ASC' if plan.sort_direction == 'ascending' else 'DESC'}"]
        return plan
