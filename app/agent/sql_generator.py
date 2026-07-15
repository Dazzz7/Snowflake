from __future__ import annotations

from app.catalog.age_bands import columns_for_age_range
from app.catalog.geography import load_states
from app.config import settings
from app.models.query_models import QueryPlan


def quote(identifier: str) -> str:
    return f'"{identifier}"'


class SQLGenerator:
    def _dynamic_age_columns(self, plan: QueryPlan) -> list[str]:
        if plan.metric.metric_id == "population_by_age" and (plan.age_min is not None or plan.age_max is not None):
            return columns_for_age_range(plan.age_min, plan.age_max)
        return []

    def _metric_expression(self, plan: QueryPlan) -> str:
        dynamic_age_columns = self._dynamic_age_columns(plan)
        if dynamic_age_columns:
            return " + ".join(quote(column) for column in dynamic_age_columns)
        if plan.metric.calculation == "sum_columns" and plan.metric.estimate_columns:
            return " + ".join(quote(column) for column in plan.metric.estimate_columns)
        if plan.metric.estimate_column:
            return quote(plan.metric.estimate_column)
        if plan.metric.estimate_columns:
            return " + ".join(quote(column) for column in plan.metric.estimate_columns)
        raise ValueError(f"Metric {plan.metric.metric_id} has no source columns")

    def _sum_expression(self, columns: list[str]) -> str:
        return " + ".join(quote(column) for column in columns)

    def _aggregate_expression(self, plan: QueryPlan) -> str:
        dynamic_age_columns = self._dynamic_age_columns(plan)
        if dynamic_age_columns:
            numerator = self._sum_expression(dynamic_age_columns)
            if plan.value_kind == "percentage":
                return f"100.0 * SUM({numerator}) / NULLIF(SUM({quote('B01003e1')}), 0)"
            return f"SUM({numerator})"
        if plan.metric.calculation == "rate":
            numerator = self._sum_expression(plan.metric.numerator_columns)
            denominator = self._sum_expression(plan.metric.denominator_columns)
            return f"100.0 * SUM({numerator}) / NULLIF(SUM({denominator}), 0)"
        if plan.metric.measure_type == "median" and plan.metric.estimate_column:
            return f"APPROX_PERCENTILE({quote(plan.metric.estimate_column)}, 0.5)"
        if plan.metric.calculation == "avg_column" and plan.metric.estimate_column:
            return f"AVG({quote(plan.metric.estimate_column)})"
        return f"SUM({self._metric_expression(plan)})"

    def _state_scope_filter(self, geo_col: str) -> str:
        fips_values = sorted({meta["state_fips"] for meta in load_states().values()})
        literals = ", ".join(f"'{fips}'" for fips in fips_values)
        return f"LEFT({geo_col}, 2) IN ({literals})"

    def _selected_geography_filter(self, plan: QueryPlan, geo_col: str) -> tuple[str, dict]:
        item = plan.geography_filters[0]
        if item.get("filter_method") == "county_set":
            county_fips = item.get("county_fips", [])
            placeholders = ", ".join(f"%(county_{index})s" for index, _ in enumerate(county_fips))
            return (
                f"LEFT({geo_col}, 5) IN ({placeholders})",
                {f"county_{index}": fips for index, fips in enumerate(county_fips)},
            )
        return f"LEFT({geo_col}, 2) = %(state_fips)s", {"state_fips": item["fips"]}

    def generate(self, plan: QueryPlan) -> QueryPlan:
        database = quote(settings.snowflake_database)
        schema = quote(settings.snowflake_schema)
        table = quote(plan.metric.table)
        geo_col = quote(plan.metric.geography_column)
        aggregate_expression = self._aggregate_expression(plan)

        if plan.query_type == "retail_gap_analysis":
            item = plan.geography_filters[0]
            county_fips = item.get("county_fips", [])
            county_placeholders = ", ".join(f"%(county_{index})s" for index, _ in enumerate(county_fips))
            parameters = {f"county_{index}": fips for index, fips in enumerate(county_fips)}
            parameters["income_threshold"] = plan.analysis_params.get("income_threshold")
            parameters["income_percentile"] = plan.analysis_params.get("income_percentile", 0.8)
            sql = f"""
WITH city_income AS (
    SELECT
        "CENSUS_BLOCK_GROUP" AS census_block_group,
        "B19013e1" AS median_household_income
    FROM {database}.{schema}."2020_CBG_B19"
    WHERE LEFT("CENSUS_BLOCK_GROUP", 5) IN ({county_placeholders})
      AND "B19013e1" IS NOT NULL
      AND "B19013e1" > 0
      AND "B19013e1" < 1000000
),
income_cutoff AS (
    SELECT
        COALESCE(%(income_threshold)s, APPROX_PERCENTILE(median_household_income, %(income_percentile)s)) AS income_cutoff
    FROM city_income
),
high_income_cbg AS (
    SELECT
        city_income.census_block_group,
        city_income.median_household_income,
        income_cutoff.income_cutoff
    FROM city_income
    CROSS JOIN income_cutoff
    WHERE city_income.median_household_income >= income_cutoff.income_cutoff
),
ranked_neighborhoods AS (
    SELECT
        high_income_cbg.census_block_group,
        high_income_cbg.median_household_income,
        high_income_cbg.income_cutoff,
        AVG({quote("DISTANCE_FROM_HOME")}) AS avg_distance_from_home_meters,
        SUM({quote("RAW_VISIT_COUNT")}) AS raw_visit_count,
        SUM({quote("RAW_VISITOR_COUNT")}) AS raw_visitor_count,
        COUNT(*) AS pattern_rows
    FROM high_income_cbg
    JOIN {database}.{schema}.{table} patterns
      ON patterns.{geo_col} = high_income_cbg.census_block_group
    WHERE patterns.{quote("DISTANCE_FROM_HOME")} IS NOT NULL
    GROUP BY 1, 2, 3
    HAVING COUNT(*) > 0
    ORDER BY avg_distance_from_home_meters DESC
    LIMIT {plan.row_limit or 5}
),
brand_counts AS (
    SELECT
        ranked_neighborhoods.census_block_group,
        flattened_brand.value::STRING AS brand,
        COUNT(*) AS brand_mentions
    FROM ranked_neighborhoods
    JOIN {database}.{schema}.{table} patterns
      ON patterns.{geo_col} = ranked_neighborhoods.census_block_group,
      LATERAL FLATTEN(input => patterns.{quote("TOP_BRANDS")}) flattened_brand
    WHERE flattened_brand.value IS NOT NULL
    GROUP BY 1, 2
),
brand_ranked AS (
    SELECT
        census_block_group,
        brand,
        brand_mentions,
        ROW_NUMBER() OVER (
            PARTITION BY census_block_group
            ORDER BY brand_mentions DESC, brand
        ) AS brand_rank
    FROM brand_counts
)
SELECT
    ranked_neighborhoods.census_block_group,
    ranked_neighborhoods.median_household_income,
    ranked_neighborhoods.income_cutoff,
    ranked_neighborhoods.avg_distance_from_home_meters,
    ranked_neighborhoods.raw_visit_count,
    ranked_neighborhoods.raw_visitor_count,
    ranked_neighborhoods.pattern_rows,
    LISTAGG(brand_ranked.brand || ' (' || brand_ranked.brand_mentions || ')', ', ')
        WITHIN GROUP (ORDER BY brand_ranked.brand_mentions DESC, brand_ranked.brand) AS top_brands
FROM ranked_neighborhoods
LEFT JOIN brand_ranked
  ON ranked_neighborhoods.census_block_group = brand_ranked.census_block_group
 AND brand_ranked.brand_rank <= 5
GROUP BY 1, 2, 3, 4, 5, 6, 7
ORDER BY avg_distance_from_home_meters DESC
""".strip()
            plan.parameters = parameters
            plan.sql = sql
            return plan

        if plan.query_type == "ranking":
            direction = "ASC" if plan.sort_direction == "ascending" else "DESC"
            limit_clause = f"LIMIT 1 OFFSET {plan.result_rank - 1}" if plan.result_rank else f"LIMIT {plan.row_limit or 10}"
            group_expr = f"LEFT({geo_col}, 5)" if plan.geography_level == "county" else f"LEFT({geo_col}, 2)"
            id_alias = "county_fips" if plan.geography_level == "county" else "state_fips"
            where_conditions = []
            parameters = {}
            if plan.geography_filters:
                where_clause_text, parameters = self._selected_geography_filter(plan, geo_col)
                where_conditions.append(where_clause_text)
            elif plan.geography_level == "state":
                where_conditions.append(self._state_scope_filter(geo_col))
            where_clause = f"WHERE {' AND '.join(where_conditions)}" if where_conditions else ""
            sql = f"""
SELECT
    {group_expr} AS {id_alias},
    {aggregate_expression} AS value
FROM {database}.{schema}.{table}
{where_clause}
GROUP BY 1
ORDER BY value {direction}
{limit_clause}
""".strip()
            plan.parameters = parameters
            plan.sql = sql
            return plan

        if plan.query_type == "filter":
            operator = plan.threshold_operator or ">"
            group_expr = f"LEFT({geo_col}, 5)" if plan.geography_level == "county" else f"LEFT({geo_col}, 2)"
            id_alias = "county_fips" if plan.geography_level == "county" else "state_fips"
            where_conditions = []
            parameters = {"threshold_value": plan.threshold_value}
            if plan.geography_level == "county" and plan.geography_filters:
                where_conditions.append(f"LEFT({geo_col}, 2) = %(parent_state_fips)s")
                parameters["parent_state_fips"] = plan.geography_filters[0]["fips"]
            elif plan.geography_level == "state":
                where_conditions.append(self._state_scope_filter(geo_col))
            where_clause = f"\nWHERE {' AND '.join(where_conditions)}" if where_conditions else ""
            plan.parameters = parameters
            sql = f"""
SELECT
    {group_expr} AS {id_alias},
    {aggregate_expression} AS value
FROM {database}.{schema}.{table}
{where_clause}
GROUP BY 1
HAVING {aggregate_expression} {operator} %(threshold_value)s
ORDER BY value DESC
LIMIT {plan.row_limit or 100}
""".strip()
            plan.sql = sql
            return plan

        if plan.query_type == "age_breakdown":
            where_clause, parameters = self._selected_geography_filter(plan, geo_col)
            sql = f"""
SELECT
    SUM("B01001e3" + "B01001e27") AS under_5,
    SUM("B01001e4" + "B01001e28") AS age_5_to_9,
    SUM("B01001e5" + "B01001e29") AS age_10_to_14,
    SUM("B01001e6" + "B01001e30") AS age_15_to_17,
    SUM("B01001e7" + "B01001e8" + "B01001e9" + "B01001e10" + "B01001e31" + "B01001e32" + "B01001e33" + "B01001e34") AS age_18_to_24,
    SUM("B01001e11" + "B01001e12" + "B01001e35" + "B01001e36") AS age_25_to_34,
    SUM("B01001e13" + "B01001e14" + "B01001e37" + "B01001e38") AS age_35_to_44,
    SUM("B01001e15" + "B01001e16" + "B01001e39" + "B01001e40") AS age_45_to_54,
    SUM("B01001e17" + "B01001e18" + "B01001e19" + "B01001e41" + "B01001e42" + "B01001e43") AS age_55_to_64,
    SUM("B01001e20" + "B01001e21" + "B01001e22" + "B01001e23" + "B01001e24" + "B01001e25" + "B01001e44" + "B01001e45" + "B01001e46" + "B01001e47" + "B01001e48" + "B01001e49") AS age_65_plus
FROM {database}.{schema}."2020_CBG_B01"
WHERE {where_clause}
""".strip()
            plan.parameters = parameters
            plan.sql = sql
            return plan

        if plan.query_type == "race_breakdown":
            where_clause, parameters = self._selected_geography_filter(plan, geo_col)
            sql = f"""
SELECT
    SUM("B02001e2") AS white_alone,
    SUM("B02001e3") AS black_or_african_american_alone,
    SUM("B02001e4") AS american_indian_and_alaska_native_alone,
    SUM("B02001e5") AS asian_alone,
    SUM("B02001e6") AS native_hawaiian_and_other_pacific_islander_alone,
    SUM("B02001e7") AS some_other_race_alone,
    SUM("B02001e8") AS two_or_more_races
FROM {database}.{schema}."2020_CBG_B02"
WHERE {where_clause}
""".strip()
            plan.parameters = parameters
            plan.sql = sql
            return plan

        if plan.query_type == "comparison":
            if all(item["type"] == "state" for item in plan.geography_filters):
                fips_codes = [item["fips"] for item in plan.geography_filters]
                placeholders = ", ".join(f"%(fips_{i})s" for i, _ in enumerate(fips_codes))
                sql = f"""
SELECT
    LEFT({geo_col}, 2) AS state_fips,
    {aggregate_expression} AS value
FROM {database}.{schema}.{table}
WHERE LEFT({geo_col}, 2) IN ({placeholders})
GROUP BY 1
ORDER BY value DESC
""".strip()
                plan.parameters = {f"fips_{i}": fips for i, fips in enumerate(fips_codes)}
                plan.sql = sql
                return plan

            parts = []
            parameters: dict = {}
            for index, item in enumerate(plan.geography_filters):
                if item["type"] == "state":
                    where_clause = f"LEFT({geo_col}, 2) = %(geo_{index})s"
                    parameters[f"geo_{index}"] = item["fips"]
                elif item.get("filter_method") == "county_set":
                    county_fips = item.get("county_fips", [])
                    placeholders = ", ".join(f"%(geo_{index}_{county_index})s" for county_index, _ in enumerate(county_fips))
                    where_clause = f"LEFT({geo_col}, 5) IN ({placeholders})"
                    parameters.update({f"geo_{index}_{county_index}": fips for county_index, fips in enumerate(county_fips)})
                else:
                    continue
                parts.append(
                    f"""
SELECT
    '{item["name"]}' AS geography_name,
    {aggregate_expression} AS value
FROM {database}.{schema}.{table}
WHERE {where_clause}
""".strip()
                )
            sql = "\nUNION ALL\n".join(parts) + "\nORDER BY value DESC"
            plan.parameters = parameters
            plan.sql = sql
            return plan

        sql = f"""
SELECT
    {aggregate_expression} AS value
FROM {database}.{schema}.{table}
WHERE {self._selected_geography_filter(plan, geo_col)[0]}
""".strip()
        plan.parameters = self._selected_geography_filter(plan, geo_col)[1]
        plan.sql = sql
        return plan
