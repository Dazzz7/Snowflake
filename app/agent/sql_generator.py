from __future__ import annotations

from app.config import settings
from app.models.query_models import QueryPlan


def quote(identifier: str) -> str:
    return f'"{identifier}"'


class SQLGenerator:
    def _metric_expression(self, plan: QueryPlan) -> str:
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
        if plan.metric.calculation == "rate":
            numerator = self._sum_expression(plan.metric.numerator_columns)
            denominator = self._sum_expression(plan.metric.denominator_columns)
            return f"100.0 * SUM({numerator}) / NULLIF(SUM({denominator}), 0)"
        if plan.metric.measure_type == "median" and plan.metric.estimate_column:
            return f"APPROX_PERCENTILE({quote(plan.metric.estimate_column)}, 0.5)"
        return f"SUM({self._metric_expression(plan)})"

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
        metric_expression = self._metric_expression(plan)
        aggregate_expression = self._aggregate_expression(plan)

        if plan.query_type == "ranking":
            direction = "ASC" if plan.sort_direction == "ascending" else "DESC"
            limit_clause = f"LIMIT 1 OFFSET {plan.result_rank - 1}" if plan.result_rank else f"LIMIT {plan.row_limit or 10}"
            sql = f"""
SELECT
    LEFT({geo_col}, 2) AS state_fips,
    {aggregate_expression} AS value
FROM {database}.{schema}.{table}
GROUP BY 1
ORDER BY value {direction}
{limit_clause}
""".strip()
            plan.sql = sql
            return plan

        if plan.query_type == "filter":
            operator = plan.threshold_operator or ">"
            group_expr = f"LEFT({geo_col}, 5)" if plan.geography_level == "county" else f"LEFT({geo_col}, 2)"
            id_alias = "county_fips" if plan.geography_level == "county" else "state_fips"
            where_clause = ""
            if plan.geography_level == "county" and plan.geography_filters:
                where_clause = f'\nWHERE LEFT({geo_col}, 2) = %(parent_state_fips)s'
                plan.parameters = {"parent_state_fips": plan.geography_filters[0]["fips"], "threshold_value": plan.threshold_value}
            else:
                plan.parameters = {"threshold_value": plan.threshold_value}
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
