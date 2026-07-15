from __future__ import annotations

import re
from typing import Any

from app.agent.hosted_llm_client import HostedLLMClient
from app.catalog.catalog_search import summarize_schema_matches
from app.catalog.geography import find_geographies
from app.config import settings
from app.database.schema_loader import search_columns_metadata, search_variable_metadata
from app.models.query_models import MetricDefinition, QueryPlan, ValidationResult


NUMERIC_TYPES = {"NUMBER", "FLOAT", "DOUBLE", "REAL", "DECIMAL", "INT", "INTEGER"}
ALLOWED_AGGREGATIONS = {"sum", "avg", "approx_median"}
ALLOWED_OPERATIONS = {"ranking", "aggregate_metric", "filter", "comparison"}
ALLOWED_GEOGRAPHY_LEVELS = {"state", "county", "block_group"}
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
        schema_result = search_variable_metadata(question, year=2020, limit=60)
        discovery_source = "field_descriptions"
        if schema_result.error or not schema_result.rows:
            schema_result = search_columns_metadata(question, limit=30)
            discovery_source = "information_schema"
        diagnostics = {
            "schema_query_id": schema_result.query_id,
            "schema_error": schema_result.error,
            "discovery_source": discovery_source,
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
        contract = self._repair_contract_from_metadata(question, contract, candidates)
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
        if row.get("IS_MARGIN_OF_ERROR") is True or str(row.get("IS_MARGIN_OF_ERROR")).lower() == "true":
            return False
        if row.get("IS_ESTIMATE") is False or str(row.get("IS_ESTIMATE")).lower() == "false":
            return False
        return _is_numeric(row)

    def _contract_from_llm(self, question: str, candidates: list[dict[str, Any]]) -> dict | None:
        if not self.llm:
            return None
        candidate_payload = summarize_schema_matches(candidates, limit=20)
        system = (
            "You propose a constrained Census analytics contract from live schema candidates. "
            "Return strict JSON only. Do not write SQL. Choose only a table and column from candidates. "
            "Allowed operations: ranking, aggregate_metric, filter, comparison. Allowed geography levels: state, county, block_group. "
            "Allowed aggregations: sum, avg, approx_median, rate. Use sum for additive counts, avg for distances/rates/means, "
            "and approx_median only when the user asks for a median-like column. If unclear, set needs_clarification true."
        )
        payload = self.llm.generate_json(
            system,
            (
                f"Question: {question}\n"
                f"Candidates: {candidate_payload}\n"
                "Return keys: needs_clarification, clarification_question, operation, table, value_column, "
                "geography_column, geography_level, aggregation, display_name, unit, sort_direction, limit, "
                "threshold_operator, threshold_value, denominator_columns. Use value_columns when a metric is represented by multiple additive variables."
            ),
        )
        return payload if isinstance(payload, dict) else None

    def _contract_deterministically(self, question: str, candidates: list[dict[str, Any]]) -> dict:
        lowered = question.lower()
        selected_candidates = self._select_deterministic_candidates(lowered, candidates)
        candidate = selected_candidates[0]
        columns = [_normal(row.get("COLUMN_NAME") or row.get("column_name")) for row in selected_candidates]
        aggregation = "sum"
        if any(term in lowered for term in ["average", "avg", "mean", "distance", "rate", "percent", "percentage"]):
            aggregation = "avg"
        if "median" in lowered:
            aggregation = "approx_median"
        operation = "aggregate_metric"
        if any(term in lowered for term in ["highest", "lowest", "top", "rank", "most", "least", "fewest"]):
            operation = "ranking"
        if any(term in lowered for term in ["compare", "versus", " vs "]):
            operation = "comparison"
        if any(term in lowered for term in ["more than", "less than", "over", "under"]) and re.search(r"\d", lowered):
            operation = "filter"
        sort_direction = "ascending" if any(term in lowered for term in ["lowest", "least", "fewest", "smallest"]) else "descending"
        geography_level = self._geography_level_from_question(lowered)
        threshold_operator, threshold_value = self._threshold_from_question(lowered)
        return {
            "needs_clarification": False,
            "operation": operation,
            "table": _normal(candidate.get("TABLE_NAME") or candidate.get("table_name")),
            "value_column": columns[0],
            "value_columns": columns,
            "geography_column": "CENSUS_BLOCK_GROUP",
            "geography_level": geography_level,
            "aggregation": aggregation,
            "display_name": self._display_name_from_candidates(selected_candidates),
            "metric_definition": _normal(candidate.get("CONCEPT") or candidate.get("concept")) or self._display_name_from_candidates(selected_candidates),
            "universe": _normal(candidate.get("UNIVERSE") or candidate.get("universe")) or "Live Snowflake metadata-derived Census Block Group column",
            "selected_variable_labels": {
                _normal(row.get("COLUMN_NAME") or row.get("column_name")).upper(): _normal(row.get("LABEL") or row.get("label"))
                for row in selected_candidates
            },
            "unit": "value",
            "sort_direction": sort_direction,
            "limit": self._limit_from_question(lowered),
            "threshold_operator": threshold_operator,
            "threshold_value": threshold_value,
        }

    def _geography_level_from_question(self, lowered: str) -> str:
        if "block group" in lowered or "block groups" in lowered or "cbg" in lowered:
            return "block_group"
        if "county" in lowered or "counties" in lowered:
            return "county"
        return "state"

    def _limit_from_question(self, lowered: str) -> int:
        match = re.search(r"\btop\s+(\d+)\b", lowered)
        if match:
            return int(match.group(1))
        if "block group" in lowered or "block groups" in lowered or "county" in lowered or "counties" in lowered:
            return 100
        return 5 if "top" in lowered else 1

    def _threshold_from_question(self, lowered: str) -> tuple[str | None, float | None]:
        match = re.search(r"\b(more than|over|above|greater than)\s+\$?([\d,.]+)\s*(million|m)?\b", lowered)
        if match:
            value = float(match.group(2).replace(",", ""))
            if match.group(3):
                value *= 1_000_000
            return ">", value
        match = re.search(r"\b(less than|under|below|fewer than)\s+\$?([\d,.]+)\s*(million|m)?\b", lowered)
        if match:
            value = float(match.group(2).replace(",", ""))
            if match.group(3):
                value *= 1_000_000
            return "<", value
        return None, None

    def _select_deterministic_candidates(self, lowered: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if "veteran" in lowered:
            veteran_rows = [
                row
                for row in candidates
                if self._label_parts(row)
                and self._label_parts(row)[-1].lower() == "veteran"
                and "nonveteran" not in " ".join(self._label_parts(row)).lower()
            ]
            total_veteran_rows = [
                row
                for row in veteran_rows
                if "male" not in [part.lower() for part in self._label_parts(row)]
                and "female" not in [part.lower() for part in self._label_parts(row)]
            ]
            if total_veteran_rows:
                return total_veteran_rows[:1]
            if veteran_rows:
                return veteran_rows
        return [candidates[0]]

    def _repair_contract_from_metadata(self, question: str, contract: dict, candidates: list[dict[str, Any]]) -> dict:
        lowered = question.lower()
        if "veteran" not in lowered:
            if self._is_rental_units_question(lowered):
                return self._repair_rental_units_contract(question, contract, candidates)
            return contract
        veteran_rows = self._select_deterministic_candidates(lowered, candidates)
        if not veteran_rows:
            return contract
        first = veteran_rows[0]
        columns = [_normal(row.get("COLUMN_NAME") or row.get("column_name")) for row in veteran_rows]
        denominator_columns = self._denominator_columns_for_veterans(lowered, candidates, veteran_rows)
        wants_rate = any(term in lowered for term in ["percent", "percentage", "rate", "share"])
        repaired = dict(contract)
        repaired.update(
            {
                "operation": self._operation_from_question(lowered),
                "table": _normal(first.get("TABLE_NAME") or first.get("table_name")),
                "value_column": columns[0],
                "value_columns": columns,
                "geography_column": "CENSUS_BLOCK_GROUP",
                "aggregation": "rate" if wants_rate and denominator_columns else "sum",
                "display_name": "Veteran share" if wants_rate and denominator_columns else "Veteran population",
                "metric_definition": _normal(first.get("CONCEPT") or first.get("concept")),
                "universe": _normal(first.get("UNIVERSE") or first.get("universe")),
                "selected_variable_labels": {
                    _normal(row.get("COLUMN_NAME") or row.get("column_name")).upper(): _normal(row.get("LABEL") or row.get("label"))
                    for row in veteran_rows
                },
            }
        )
        if wants_rate and denominator_columns:
            repaired["denominator_columns"] = denominator_columns
            repaired["unit"] = "%"
        if not repaired.get("geography_level"):
            repaired["geography_level"] = self._geography_level_from_question(lowered)
        if not repaired.get("sort_direction"):
            repaired["sort_direction"] = "descending"
        if not repaired.get("limit"):
            repaired["limit"] = 1
        if not wants_rate:
            repaired["unit"] = "people"
        return repaired

    def _is_rental_units_question(self, lowered: str) -> bool:
        return any(term in lowered for term in ["rental", "renter", "rent"]) and any(term in lowered for term in ["unit", "units", "housing"])

    def _repair_rental_units_contract(self, question: str, contract: dict, candidates: list[dict[str, Any]]) -> dict:
        lowered = question.lower()
        rental_rows = self._find_rental_unit_rows(candidates)
        if not rental_rows:
            targeted_result = search_variable_metadata("tenure renter occupied housing units", year=2020, limit=80)
            if not targeted_result.error:
                rental_rows = self._find_rental_unit_rows([row for row in targeted_result.rows if self._candidate_is_eligible(row)])
                if rental_rows:
                    candidates.extend(row for row in rental_rows if row not in candidates)
        if not rental_rows:
            return contract
        first = rental_rows[0]
        column = _normal(first.get("COLUMN_NAME") or first.get("column_name"))
        threshold_operator, threshold_value = self._threshold_from_question(lowered)
        repaired = dict(contract)
        repaired.update(
            {
                "operation": self._operation_from_question(lowered),
                "table": _normal(first.get("TABLE_NAME") or first.get("table_name")),
                "value_column": column,
                "value_columns": [column],
                "geography_column": "CENSUS_BLOCK_GROUP",
                "geography_level": self._geography_level_from_question(lowered),
                "aggregation": "sum",
                "display_name": "Renter-occupied housing units",
                "metric_definition": _normal(first.get("CONCEPT") or first.get("concept")),
                "universe": _normal(first.get("UNIVERSE") or first.get("universe")),
                "selected_variable_labels": {
                    column.upper(): _normal(first.get("LABEL") or first.get("label")),
                },
                "unit": "housing units",
                "sort_direction": "descending",
                "limit": self._limit_from_question(lowered),
                "threshold_operator": threshold_operator,
                "threshold_value": threshold_value,
            }
        )
        return repaired

    def _find_rental_unit_rows(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rental_rows = [
            row
            for row in candidates
            if _normal(row.get("CONCEPT") or row.get("concept")).lower() == "tenure"
            and self._label_parts(row)
            and self._label_parts(row)[-1].lower() == "renter occupied"
            and "householder" not in " ".join(self._label_parts(row)).lower()
        ]
        if not rental_rows:
            rental_rows = [
                row
                for row in candidates
                if self._label_parts(row)
                and self._label_parts(row)[-1].lower() == "renter occupied"
                and _normal(row.get("UNIVERSE") or row.get("universe")).lower() == "occupied housing units"
            ]
        return rental_rows

    def _operation_from_question(self, lowered: str) -> str:
        if any(term in lowered for term in ["compare", "versus", " vs "]):
            return "comparison"
        if any(term in lowered for term in ["highest", "lowest", "top", "rank", "most", "least", "fewest"]):
            return "ranking"
        if any(term in lowered for term in ["more than", "less than", "over", "under"]) and re.search(r"\d", lowered):
            return "filter"
        return "aggregate_metric"

    def _denominator_columns_for_veterans(
        self,
        lowered: str,
        candidates: list[dict[str, Any]],
        numerator_rows: list[dict[str, Any]],
    ) -> list[str]:
        if not any(term in lowered for term in ["percent", "percentage", "rate", "share"]):
            return []
        numerator_table_numbers = {
            _normal(row.get("TABLE_NUMBER") or row.get("table_number"))
            for row in numerator_rows
            if _normal(row.get("TABLE_NUMBER") or row.get("table_number"))
        }
        numerator_concepts = {
            _normal(row.get("CONCEPT") or row.get("concept"))
            for row in numerator_rows
            if _normal(row.get("CONCEPT") or row.get("concept"))
        }
        total_rows = []
        for row in candidates:
            table_number = _normal(row.get("TABLE_NUMBER") or row.get("table_number"))
            concept = _normal(row.get("CONCEPT") or row.get("concept"))
            if numerator_table_numbers and table_number not in numerator_table_numbers:
                continue
            if not numerator_table_numbers and numerator_concepts and concept not in numerator_concepts:
                continue
            parts = [part.lower() for part in self._label_parts(row)]
            if parts and parts[-1] == "total" and "male" not in parts and "female" not in parts:
                total_rows.append(row)
        return [_normal(row.get("COLUMN_NAME") or row.get("column_name")) for row in total_rows[:1]]

    def _label_parts(self, row: dict[str, Any]) -> list[str]:
        label = _normal(row.get("LABEL") or row.get("label"))
        return [part.strip() for part in label.split(":") if part.strip()]

    def _display_name_from_candidates(self, candidates: list[dict[str, Any]]) -> str:
        if len(candidates) > 1:
            labels = [self._label_parts(row) for row in candidates]
            if labels and all(parts and parts[-1].lower() == "veteran" for parts in labels):
                return "Veteran population"
        column = _normal(candidates[0].get("COLUMN_NAME") or candidates[0].get("column_name"))
        return column.replace("_", " ").title()

    def _validate_contract(self, question: str, contract: dict | None, candidates: list[dict[str, Any]]) -> ValidationResult:
        if not contract:
            return ValidationResult(False, "The dynamic semantic layer could not propose a contract.")
        if contract.get("needs_clarification"):
            return ValidationResult(False, contract.get("clarification_question") or "The dynamic metric request is ambiguous.")
        operation = _normal(contract.get("operation"))
        table = _normal(contract.get("table")).upper()
        value_columns = contract.get("value_columns") or [contract.get("value_column")]
        columns = [_normal(column).upper() for column in value_columns if _normal(column)]
        column = columns[0] if columns else ""
        geography_column = _normal(contract.get("geography_column") or "CENSUS_BLOCK_GROUP").upper()
        geography_level = _normal(contract.get("geography_level")).lower()
        aggregation = _normal(contract.get("aggregation")).lower()
        if operation not in ALLOWED_OPERATIONS:
            return ValidationResult(False, "The dynamic operation is not supported.")
        if geography_level not in ALLOWED_GEOGRAPHY_LEVELS:
            return ValidationResult(False, "The dynamic geography level must be state, county, or block_group.")
        if aggregation == "rate":
            denominator_columns = [_normal(column).upper() for column in contract.get("denominator_columns", []) if _normal(column)]
            if not denominator_columns:
                return ValidationResult(False, "The dynamic rate plan requires denominator columns.")
        elif aggregation not in ALLOWED_AGGREGATIONS:
            return ValidationResult(False, "The dynamic aggregation must be sum, avg, or approx_median.")
        if geography_column != "CENSUS_BLOCK_GROUP":
            return ValidationResult(False, "The dynamic plan must use CENSUS_BLOCK_GROUP as the geography key.")
        if not _is_allowed_table(table):
            return ValidationResult(False, "The dynamic table is outside the approved public CBG table allowlist.")
        candidate_keys = {_candidate_key(row) for row in candidates}
        if not columns:
            return ValidationResult(False, "The dynamic metric did not select any value columns.")
        denominator_columns = [_normal(column).upper() for column in contract.get("denominator_columns", []) if _normal(column)]
        all_selected_columns = [*columns, *denominator_columns]
        missing_columns = [(table, selected_column) for selected_column in all_selected_columns if (table, selected_column) not in candidate_keys]
        if missing_columns:
            return ValidationResult(False, "The dynamic metric column was not found in live schema candidates.")
        candidate_lookup = {_candidate_key(row): row for row in candidates}
        for selected_column in all_selected_columns:
            selected = candidate_lookup[(table, selected_column)]
            if selected.get("IS_MARGIN_OF_ERROR") is True or str(selected.get("IS_MARGIN_OF_ERROR")).lower() == "true":
                return ValidationResult(False, "A margin-of-error field was selected as a primary value.")
            label = _normal(selected.get("LABEL") or selected.get("label"))
            if label and "label_by_column" in contract:
                expected = contract["label_by_column"].get(selected_column) or contract["label_by_column"].get(selected_column.upper())
                if expected and expected != label:
                    return ValidationResult(False, "The selected variable label does not match the metadata catalog.")
        if operation in {"aggregate_metric", "comparison"} and geography_level != "block_group" and not find_geographies(question):
            return ValidationResult(False, "A selected geography is required for a dynamic lookup.")
        return ValidationResult(True)

    def _plan_from_contract(self, question: str, contract: dict) -> QueryPlan:
        aggregation = _normal(contract.get("aggregation")).lower()
        operation = _normal(contract.get("operation"))
        table = _normal(contract.get("table")).upper()
        value_columns = contract.get("value_columns") or [contract.get("value_column")]
        columns = [_normal(column) for column in value_columns if _normal(column)]
        column = columns[0]
        geography_level = _normal(contract.get("geography_level")).lower()
        unit = _unit_for_column(column, _normal(contract.get("unit") or "value"))
        contract["unit"] = unit
        denominator_columns = [_normal(column) for column in contract.get("denominator_columns", []) if _normal(column)]
        measure_type = "percentage" if aggregation == "rate" else ("median" if aggregation == "approx_median" else ("average" if aggregation == "avg" else "count"))
        calculation = {"sum": "single_column", "avg": "avg_column", "approx_median": "single_column", "rate": "rate"}[aggregation]
        if aggregation == "sum" and len(columns) > 1:
            calculation = "sum_columns"
        metric = MetricDefinition(
            metric_id=f"dynamic_{table.lower()}_{column.lower()}",
            display_name=_normal(contract.get("display_name")) or column.replace("_", " ").title(),
            description=_normal(contract.get("metric_definition")) or f"Dynamic metadata-derived metric from {table}.{column}",
            synonyms=[],
            table=table,
            geography_column="CENSUS_BLOCK_GROUP",
            aggregation=aggregation.upper(),
            aggregation_behavior="metadata_verified_dynamic",
            unit=unit,
            year=int(table[:4]) if table[:4].isdigit() else 2020,
            universe=_normal(contract.get("universe")) or "Live Snowflake metadata-derived Census Block Group column",
            verified=True,
            estimate_column=column,
            estimate_columns=columns,
            source_columns=[*columns, *denominator_columns],
            measure_type=measure_type,
            calculation=calculation,
            numerator_columns=columns if aggregation == "rate" else [],
            denominator_columns=denominator_columns,
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
            plan.group_by = ["census_block_group" if geography_level == "block_group" else ("state_fips" if geography_level == "state" else "county_fips")]
            plan.order_by = [f"value {'ASC' if plan.sort_direction == 'ascending' else 'DESC'}"]
        return plan
