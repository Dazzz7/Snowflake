from __future__ import annotations

from app.catalog.geography import load_states
from app.models.query_models import QueryPlan, ValidationResult
from app.models.response_models import QueryResult


class ResultValidator:
    def validate(self, plan: QueryPlan, result: QueryResult) -> ValidationResult:
        if result.error:
            return ValidationResult(False, result.error)
        if not result.rows:
            return ValidationResult(False, "The query returned no rows.")
        state_fips_values = {meta["state_fips"] for meta in load_states().values()}
        if plan.query_type == "age_breakdown":
            if not any(key.lower().startswith("age_") or key.lower() == "under_5" for key in result.rows[0]):
                return ValidationResult(False, "The age breakdown query did not return age-band columns.")
            return ValidationResult(True)
        if plan.query_type == "race_breakdown":
            if not any("race" in key.lower() or "white" in key.lower() for key in result.rows[0]):
                return ValidationResult(False, "The race breakdown query did not return race category columns.")
            return ValidationResult(True)
        if plan.query_type == "retail_gap_analysis":
            required_columns = {
                "CENSUS_BLOCK_GROUP",
                "MEDIAN_HOUSEHOLD_INCOME",
                "INCOME_CUTOFF",
                "AVG_DISTANCE_FROM_HOME_METERS",
                "RAW_VISIT_COUNT",
                "RAW_VISITOR_COUNT",
                "TOP_BRANDS",
            }
            row_columns = {key.upper() for key in result.rows[0]}
            missing = required_columns.difference(row_columns)
            if missing:
                return ValidationResult(False, f"The retail analysis result is missing expected columns: {', '.join(sorted(missing))}.")
            for row in result.rows:
                cbg = row.get("CENSUS_BLOCK_GROUP") or row.get("census_block_group")
                distance = row.get("AVG_DISTANCE_FROM_HOME_METERS") or row.get("avg_distance_from_home_meters")
                income = row.get("MEDIAN_HOUSEHOLD_INCOME") or row.get("median_household_income")
                if not cbg:
                    return ValidationResult(False, "The retail analysis result did not include a Census Block Group.")
                if not isinstance(distance, (int, float)) or distance < 0:
                    return ValidationResult(False, "The retail analysis returned an invalid travel-distance value.")
                if not isinstance(income, (int, float)) or not (0 < income < 1_000_000):
                    return ValidationResult(False, "The retail analysis returned an invalid income value.")
            return ValidationResult(True)
        for row in result.rows:
            value = row.get("VALUE") if "VALUE" in row else row.get("value")
            if value is None:
                return ValidationResult(False, "The dataset did not contain a usable value for that selection.")
            if isinstance(value, (int, float)) and value < 0:
                return ValidationResult(False, "The query returned an implausible negative value.")
            if plan.query_type == "ranking":
                if plan.geography_level == "county":
                    county_fips = row.get("COUNTY_FIPS") or row.get("county_fips")
                    if not county_fips:
                        return ValidationResult(False, "The county ranking result did not include a county identifier.")
                else:
                    state_fips = row.get("STATE_FIPS") or row.get("state_fips")
                    if not state_fips:
                        return ValidationResult(False, "The ranking result did not include a state identifier.")
                    if str(state_fips) not in state_fips_values:
                        return ValidationResult(False, "The ranking result included a geography outside the approved state scope.")
            if plan.query_type == "filter" and plan.geography_level == "state":
                state_fips = row.get("STATE_FIPS") or row.get("state_fips")
                if not state_fips or str(state_fips) not in state_fips_values:
                    return ValidationResult(False, "The filter result included a geography outside the approved state scope.")
            if plan.query_type == "filter" and plan.geography_level == "county":
                county_fips = row.get("COUNTY_FIPS") or row.get("county_fips")
                if not county_fips:
                    return ValidationResult(False, "The county filter result did not include a county identifier.")
            is_percentage = plan.metric.unit == "%" or (plan.metric.metric_id == "population_by_age" and plan.value_kind == "percentage")
            if is_percentage and isinstance(value, (int, float)) and not (0 <= value <= 100):
                return ValidationResult(False, "The percentage result failed a 0 to 100 sanity check.")
            if plan.metric.unit == "USD" and isinstance(value, (int, float)) and value >= 1_000_000:
                return ValidationResult(False, "The income result failed a broad sanity check.")
            if plan.metric.metric_id == "total_population" and plan.query_type == "aggregate_metric":
                if isinstance(value, (int, float)) and not (1_000 <= value <= 100_000_000):
                    return ValidationResult(False, "The population result failed a broad sanity check.")
        return ValidationResult(True)
