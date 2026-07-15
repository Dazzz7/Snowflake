from __future__ import annotations

from app.agent.evidence_renderer import build_evidence
from app.catalog.age_bands import age_range_label, columns_for_age_range
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


def _meters_to_miles(value: object) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    return value / 1609.344


def _ordinal(value: int) -> str:
    special = {1: "first", 2: "second", 3: "third"}
    if value in special:
        return special[value]
    suffix = "th" if 10 <= value % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return f"{value}{suffix}"


def _metric_label(plan: QueryPlan) -> str:
    if plan.metric.metric_id == "population_by_age" and (plan.age_min is not None or plan.age_max is not None):
        label = age_range_label(plan.age_min, plan.age_max)
        if plan.value_kind == "percentage":
            return f"Percentage of residents {label}"
        return f"Population {label}"
    return plan.metric.display_name


def _metric_unit(plan: QueryPlan) -> str:
    if plan.metric.metric_id == "population_by_age" and plan.value_kind == "percentage":
        return "%"
    return plan.metric.unit


def _source_columns(plan: QueryPlan) -> list[str]:
    if plan.metric.metric_id == "population_by_age" and (plan.age_min is not None or plan.age_max is not None):
        columns = columns_for_age_range(plan.age_min, plan.age_max)
        if plan.value_kind == "percentage":
            return [*columns, "B01003e1"]
        return columns
    return plan.metric.source_columns or plan.metric.estimate_columns


def _calculation(plan: QueryPlan) -> str:
    if plan.metric.metric_id == "population_by_age" and (plan.age_min is not None or plan.age_max is not None):
        return "dynamic_age_percentage" if plan.value_kind == "percentage" else "dynamic_age_count"
    return plan.metric.calculation


def _state_name(state_lookup: dict[str, str], fips: object) -> str:
    return state_lookup.get(str(fips), "Unknown state")


def _ranked_geography_name(plan: QueryPlan, state_lookup: dict[str, str], county_lookup: dict[str, str], row: dict) -> str:
    cbg = row.get("CENSUS_BLOCK_GROUP") or row.get("census_block_group")
    if plan.geography_level == "block_group" and cbg:
        return f"CBG {cbg}"
    county_fips = row.get("COUNTY_FIPS") or row.get("county_fips")
    if plan.geography_level == "county" and county_fips:
        return county_lookup.get(str(county_fips), "Unknown county")
    fips = row.get("STATE_FIPS") or row.get("state_fips")
    return _state_name(state_lookup, fips)


class ResponseGenerator:
    def generate(self, question: str, plan: QueryPlan, result: QueryResult) -> AgentResponse:
        state_lookup = {meta["state_fips"]: name for name, meta in load_states().items()}
        county_lookup = load_counties()
        rows = result.rows
        metric_label = _metric_label(plan)
        metric_unit = _metric_unit(plan)
        if plan.query_type == "comparison":
            parts = []
            for row in rows:
                name = row.get("GEOGRAPHY_NAME") or row.get("geography_name")
                fips = row.get("STATE_FIPS") or row.get("state_fips")
                value = row.get("VALUE") if "VALUE" in row else row.get("value")
                geography_name = name or _state_name(state_lookup, fips)
                parts.append(f"{geography_name}: {_format_value_with_unit(value, metric_unit)}")
            answer = f"Using the available {plan.metric.year} Census dataset, " + "; ".join(parts) + "."
        elif plan.query_type == "ranking":
            visible_rows = rows
            if plan.result_rank and visible_rows:
                row = visible_rows[0]
                value = row.get("VALUE") if "VALUE" in row else row.get("value")
                geography_name = _ranked_geography_name(plan, state_lookup, county_lookup, row)
                answer = (
                    f"{geography_name} ranks {_ordinal(plan.result_rank)}, with approximately "
                    + f"{_format_value_with_unit(value, metric_unit, approximate=True)} in the same {plan.metric.year} dataset."
                )
            elif plan.row_limit == 1 and visible_rows:
                row = visible_rows[0]
                value = row.get("VALUE") if "VALUE" in row else row.get("value")
                geography_name = _ranked_geography_name(plan, state_lookup, county_lookup, row)
                adjective = "lowest" if plan.sort_direction == "ascending" else "highest"
                geography_scope = "US Census Block Groups" if plan.geography_level == "block_group" else ("US counties" if plan.geography_level == "county" else "US states")
                answer = (
                    f"{geography_name} has the {adjective} {metric_label.lower()} among {geography_scope} "
                    + f"in the available {plan.metric.year} dataset, with approximately {_format_value_with_unit(value, metric_unit, approximate=True)}."
                )
            else:
                parts = []
                for index, row in enumerate(visible_rows, start=1):
                    value = row.get("VALUE") if "VALUE" in row else row.get("value")
                    parts.append(f"{index}. {_ranked_geography_name(plan, state_lookup, county_lookup, row)} ({_format_value_with_unit(value, metric_unit)})")
                answer = f"Using the available {plan.metric.year} Census dataset: " + " ".join(parts)
        elif plan.query_type == "filter":
            parts = []
            for row in rows:
                fips = row.get("STATE_FIPS") or row.get("state_fips")
                county_fips = row.get("COUNTY_FIPS") or row.get("county_fips")
                cbg = row.get("CENSUS_BLOCK_GROUP") or row.get("census_block_group")
                value = row.get("VALUE") if "VALUE" in row else row.get("value")
                if plan.geography_level == "block_group" and cbg:
                    geography_name = f"CBG {cbg}"
                else:
                    geography_name = county_lookup.get(str(county_fips), "Unknown county") if county_fips else _state_name(state_lookup, fips)
                parts.append(f"{geography_name} ({_format_value_with_unit(value, metric_unit)})")
            comparator = "more than" if plan.threshold_operator == ">" else "less than"
            geography_label = "Census Block Groups" if plan.geography_level == "block_group" else ("counties" if plan.geography_level == "county" else "states")
            answer = (
                f"Using the available {plan.metric.year} Census dataset, these {geography_label} have {comparator} "
                + f"{_format_value_with_unit(plan.threshold_value or 0, metric_unit)}: "
                + ", ".join(parts)
                + "."
            )
        elif plan.query_type == "retail_gap_analysis":
            geography = plan.geography_filters[0]["name"] if plan.geography_filters else "the target city"
            parts = []
            for index, row in enumerate(rows, start=1):
                cbg = row.get("CENSUS_BLOCK_GROUP") or row.get("census_block_group")
                income = row.get("MEDIAN_HOUSEHOLD_INCOME") or row.get("median_household_income")
                cutoff = row.get("INCOME_CUTOFF") or row.get("income_cutoff")
                distance = row.get("AVG_DISTANCE_FROM_HOME_METERS") or row.get("avg_distance_from_home_meters")
                visits = row.get("RAW_VISIT_COUNT") or row.get("raw_visit_count")
                brands = row.get("TOP_BRANDS") or row.get("top_brands") or "No brand mentions"
                miles = _meters_to_miles(distance)
                distance_text = f"{miles:,.1f} miles" if miles is not None else _format_value_with_unit(distance, "meters")
                parts.append(
                    f"{index}. CBG {cbg}: avg visitor distance {distance_text}, "
                    f"median household income {_format_value_with_unit(income, 'USD')}, "
                    f"visits {_format_number(visits)}, top brands {brands}"
                )
            cutoff_text = _format_value_with_unit(rows[0].get("INCOME_CUTOFF") or rows[0].get("income_cutoff"), "USD") if rows else "the top-income cutoff"
            answer = (
                f"Using ACS 2020 income data and 2019 venue-pattern data, these high-income Census Block Groups in {geography} "
                f"meet the income cutoff of about {cutoff_text} and have the farthest average visitor travel distances: "
                + " ".join(parts)
                + " Note: the patterns table is keyed to venue Census Block Groups, so this identifies high-income destination neighborhoods whose venues draw visitors from farther away; it does not prove that residents of those CBGs made every trip."
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
                f"{metric_label.lower()} was {_format_value_with_unit(value, metric_unit)}."
            )
        interpretation = {
                "question": question,
                "metric": metric_label,
                "year": plan.metric.year,
                "source_table": plan.metric.table,
                "source_columns": _source_columns(plan),
                "calculation": _calculation(plan),
                "operation": plan.interpretation,
                "question_type": plan.query_type,
                "geography_level": plan.geography_level,
                "scope": plan.geography_scope,
                "sort_direction": plan.sort_direction,
                "limit": plan.row_limit,
                "rank": plan.result_rank,
                "threshold": plan.threshold_value,
                "dimension": plan.dimension,
                "age_min": plan.age_min,
                "age_max": plan.age_max,
                "value_kind": plan.value_kind,
                "llm_attempted": plan.llm_attempted,
                "llm_succeeded": plan.llm_succeeded,
                "llm_provider": plan.llm_provider,
            }
        if plan.metric.estimate_column:
            interpretation["source_column"] = plan.metric.estimate_column
        if plan.metric.metric_id.startswith("dynamic_"):
            interpretation["metadata_discovery"] = True
            interpretation["metric_definition"] = plan.metric.description
            interpretation["universe"] = plan.metric.universe
            answer += f" In this dataset, the selected measure is defined as: {plan.metric.description}. Universe: {plan.metric.universe}."
        if plan.metric.measure_type == "median":
            interpretation["aggregation_note"] = (
                "This uses the configured block-group median-income field as a proxy. "
                "For an official statewide median, configure a state-grain source table if available."
            )
            answer += " Note: this is computed from the configured block-group median-income field, so treat it as a proxy unless a state-grain source is configured."
        return AgentResponse(
            answer=answer,
            interpretation=interpretation,
            evidence=build_evidence(plan, result),
            sql=plan.sql,
            rows=rows,
        )
