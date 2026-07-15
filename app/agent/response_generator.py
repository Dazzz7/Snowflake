from __future__ import annotations

from app.catalog.geography import load_counties, load_states
from app.models.query_models import QueryPlan
from app.models.response_models import AgentResponse, QueryResult


def _format_number(value: object) -> str:
    if isinstance(value, float):
        return f"{value:,.0f}" if value.is_integer() else f"{value:,.2f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _format_approx(value: object) -> str:
    if isinstance(value, (int, float)) and abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f} million"
    return _format_number(value)


def _format_value_with_unit(value: object, unit: str, approximate: bool = False) -> str:
    formatted = _format_approx(value) if approximate else _format_number(value)
    if unit == "%":
        return f"{formatted}%"
    return f"{formatted} {unit}"


def _ordinal(value: int) -> str:
    special = {1: "first", 2: "second", 3: "third"}
    if value in special:
        return special[value]
    suffix = "th" if 10 <= value % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return f"{value}{suffix}"


class ResponseGenerator:
    def generate(self, question: str, plan: QueryPlan, result: QueryResult) -> AgentResponse:
        state_lookup = {meta["state_fips"]: name for name, meta in load_states().items()}
        county_lookup = load_counties()
        rows = result.rows
        if plan.query_type == "comparison":
            parts = []
            for row in rows:
                name = row.get("GEOGRAPHY_NAME") or row.get("geography_name")
                fips = row.get("STATE_FIPS") or row.get("state_fips")
                value = row.get("VALUE") if "VALUE" in row else row.get("value")
                geography_name = name or state_lookup.get(str(fips), str(fips))
                parts.append(f"{geography_name}: {_format_value_with_unit(value, plan.metric.unit)}")
            answer = f"Using the available {plan.metric.year} Census dataset, " + "; ".join(parts) + "."
        elif plan.query_type == "ranking":
            visible_rows = rows
            if plan.result_rank and visible_rows:
                row = visible_rows[0]
                fips = row.get("STATE_FIPS") or row.get("state_fips")
                value = row.get("VALUE") if "VALUE" in row else row.get("value")
                state_name = state_lookup.get(str(fips), str(fips))
                answer = (
                    f"{state_name} ranks {_ordinal(plan.result_rank)}, with approximately "
                    + f"{_format_value_with_unit(value, plan.metric.unit, approximate=True)} in the same {plan.metric.year} dataset."
                )
            elif plan.row_limit == 1 and visible_rows:
                row = visible_rows[0]
                fips = row.get("STATE_FIPS") or row.get("state_fips")
                value = row.get("VALUE") if "VALUE" in row else row.get("value")
                state_name = state_lookup.get(str(fips), str(fips))
                adjective = "lowest" if plan.sort_direction == "ascending" else "highest"
                answer = (
                    f"{state_name} has the {adjective} {plan.metric.display_name.lower()} among US states "
                    + f"in the available {plan.metric.year} dataset, with approximately {_format_value_with_unit(value, plan.metric.unit, approximate=True)}."
                )
            else:
                parts = []
                for index, row in enumerate(visible_rows, start=1):
                    fips = row.get("STATE_FIPS") or row.get("state_fips")
                    value = row.get("VALUE") if "VALUE" in row else row.get("value")
                    parts.append(f"{index}. {state_lookup.get(str(fips), str(fips))} ({_format_value_with_unit(value, plan.metric.unit)})")
                answer = f"Using the available {plan.metric.year} Census dataset: " + " ".join(parts)
        elif plan.query_type == "filter":
            parts = []
            for row in rows:
                fips = row.get("STATE_FIPS") or row.get("state_fips")
                county_fips = row.get("COUNTY_FIPS") or row.get("county_fips")
                value = row.get("VALUE") if "VALUE" in row else row.get("value")
                geography_name = county_lookup.get(str(county_fips), str(county_fips)) if county_fips else state_lookup.get(str(fips), str(fips))
                parts.append(f"{geography_name} ({_format_number(value)})")
            comparator = "more than" if plan.threshold_operator == ">" else "less than"
            geography_label = "counties" if plan.geography_level == "county" else "states"
            answer = (
                f"Using the available {plan.metric.year} Census dataset, these {geography_label} have {comparator} "
                + f"{_format_value_with_unit(plan.threshold_value or 0, plan.metric.unit)}: "
                + ", ".join(parts)
                + "."
            )
        elif plan.query_type == "age_breakdown":
            row = rows[0]
            labels = [
                ("UNDER_5", "Under 5"),
                ("AGE_5_TO_9", "5-9"),
                ("AGE_10_TO_14", "10-14"),
                ("AGE_15_TO_17", "15-17"),
                ("AGE_18_TO_24", "18-24"),
                ("AGE_25_TO_34", "25-34"),
                ("AGE_35_TO_44", "35-44"),
                ("AGE_45_TO_54", "45-54"),
                ("AGE_55_TO_64", "55-64"),
                ("AGE_65_PLUS", "65+"),
            ]
            geography = plan.geography_filters[0]["name"]
            parts = [f"{label}: {_format_number(row.get(key, row.get(key.lower(), 0)))}" for key, label in labels]
            answer = f"Using the available {plan.metric.year} Census age table, {geography}'s age breakdown is: " + "; ".join(parts) + "."
        elif plan.query_type == "race_breakdown":
            row = rows[0]
            labels = [
                ("WHITE_ALONE", "White alone"),
                ("BLACK_OR_AFRICAN_AMERICAN_ALONE", "Black or African American alone"),
                ("AMERICAN_INDIAN_AND_ALASKA_NATIVE_ALONE", "American Indian and Alaska Native alone"),
                ("ASIAN_ALONE", "Asian alone"),
                ("NATIVE_HAWAIIAN_AND_OTHER_PACIFIC_ISLANDER_ALONE", "Native Hawaiian and Other Pacific Islander alone"),
                ("SOME_OTHER_RACE_ALONE", "Some other race alone"),
                ("TWO_OR_MORE_RACES", "Two or more races"),
            ]
            geography = plan.geography_filters[0]["name"]
            parts = [f"{label}: {_format_number(row.get(key, row.get(key.lower(), 0)))}" for key, label in labels]
            answer = f"Using the available {plan.metric.year} Census race table, {geography}'s racial distribution is: " + "; ".join(parts) + "."
        else:
            value = rows[0].get("VALUE") if "VALUE" in rows[0] else rows[0].get("value")
            geography = plan.geography_filters[0]["name"]
            answer = (
                f"Using the available {plan.metric.year} Census dataset, {geography}'s "
                f"{plan.metric.display_name.lower()} was {_format_value_with_unit(value, plan.metric.unit)}."
            )
        interpretation = {
                "question": question,
                "metric": plan.metric.display_name,
                "year": plan.metric.year,
                "source_table": plan.metric.table,
                "source_columns": plan.metric.source_columns or plan.metric.estimate_columns,
                "calculation": plan.metric.calculation,
                "operation": plan.interpretation,
                "question_type": plan.query_type,
                "geography_level": plan.geography_level,
                "scope": plan.geography_scope,
                "sort_direction": plan.sort_direction,
                "limit": plan.row_limit,
                "rank": plan.result_rank,
                "threshold": plan.threshold_value,
                "dimension": plan.dimension,
                "llm_attempted": plan.llm_attempted,
                "llm_succeeded": plan.llm_succeeded,
                "llm_provider": plan.llm_provider,
            }
        if plan.metric.estimate_column:
            interpretation["source_column"] = plan.metric.estimate_column
        if plan.metric.measure_type == "median":
            interpretation["aggregation_note"] = (
                "This uses the configured block-group median-income field as a proxy. "
                "For an official statewide median, configure a state-grain source table if available."
            )
            answer += " Note: this is computed from the configured block-group median-income field, so treat it as a proxy unless a state-grain source is configured."
        return AgentResponse(
            answer=answer,
            interpretation=interpretation,
            sql=plan.sql,
            rows=rows,
        )
