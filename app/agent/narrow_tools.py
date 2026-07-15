from __future__ import annotations

import re
from typing import Any

from app.catalog.geography import find_geographies, load_states
from app.config import settings
from app.database.query_executor import SnowflakeQueryExecutor
from app.database.schema_loader import search_variable_metadata
from app.models.response_models import QueryResult


GEOGRAPHY_TABLE = "2020_METADATA_CBG_GEOGRAPHIC_DATA"

TABLE_NAME_PATTERN = re.compile(r"^2020_CBG_[A-Z0-9]{3}$", re.IGNORECASE)

GEOGRAPHY_COLUMNS = {
    "CENSUS_BLOCK_GROUP": "Census Block Group identifier",
    "AMOUNT_LAND": "Land area",
    "AMOUNT_WATER": "Water area",
    "LATITUDE": "Latitude",
    "LONGITUDE": "Longitude",
}


def search_metadata(query: str, top_k: int = 40) -> dict[str, Any]:
    top_k = max(1, min(top_k, 80))
    rows: list[dict[str, Any]] = []
    result = search_variable_metadata(query, year=2020, limit=max(top_k, 60))
    if not result.error:
        for row in result.rows:
            table = str(row.get("TABLE_NAME") or row.get("table_name") or "").upper()
            if not _is_census_data_table(table):
                continue
            if str(row.get("IS_MARGIN_OF_ERROR")).lower() == "true":
                continue
            rows.append(_metadata_row(row))

    if _looks_like_land_or_geography(query):
        for column, label in GEOGRAPHY_COLUMNS.items():
            if column == "CENSUS_BLOCK_GROUP" or _column_matches_query(column, label, query):
                rows.append(
                    {
                        "table_name": "2020_METADATA_CBG_GEOGRAPHIC_DATA",
                        "column_name": column,
                        "data_type": "NUMBER" if column != "CENSUS_BLOCK_GROUP" else "TEXT",
                        "concept": "Census geography",
                        "label": label,
                        "universe": "Census Block Groups",
                        "year": 2020,
                        "category": "land geography",
                        "geography_grain": "Census Block Group",
                        "geography_column": "CENSUS_BLOCK_GROUP",
                    }
                )
    return {"results": _dedupe_metadata_rows(rows)[:top_k], "error": result.error}


def describe_table(table_name: str) -> dict[str, Any]:
    table = table_name.upper()
    if not _is_allowed_table_name(table):
        return {"error": "Table is outside the retrieved Census metadata scope.", "table_name": table_name}
    if table == GEOGRAPHY_TABLE:
        return {
            "table_name": table,
            "description": "Census Block Group geography and land/water area",
            "geography_grain": "Census Block Group",
            "geography_column": "CENSUS_BLOCK_GROUP",
            "columns": [
                {
                    "column_name": column,
                    "data_type": "NUMBER" if column != "CENSUS_BLOCK_GROUP" else "TEXT",
                    "concept": "Census geography",
                    "label": label,
                    "universe": "Census Block Groups",
                    "year": 2020,
                }
                for column, label in GEOGRAPHY_COLUMNS.items()
            ],
        }

    table_number = table.removeprefix("2020_CBG_")
    sql = f"""
SELECT
    table_id AS column_name,
    table_title AS concept,
    ARRAY_TO_STRING(
        ARRAY_CONSTRUCT_COMPACT(
            field_level_1,
            field_level_2,
            field_level_3,
            field_level_4,
            field_level_5,
            field_level_6,
            field_level_7,
            field_level_8,
            "FIELD_LEVELl_9",
            field_level_10
        ),
        ': '
    ) AS label,
    table_universe AS universe,
    table_topics AS category,
    2020 AS year
FROM {settings.snowflake_database}.PUBLIC."2020_METADATA_CBG_FIELD_DESCRIPTIONS"
WHERE table_number LIKE %(table_number)s
  AND REGEXP_LIKE(table_id, '.*e[0-9]+$', 'i')
ORDER BY table_id
LIMIT 250
""".strip()
    result = SnowflakeQueryExecutor().execute(sql, {"table_number": f"{table_number}%"})
    columns = [
        {
            "column_name": "CENSUS_BLOCK_GROUP",
            "data_type": "TEXT",
            "concept": "Census geography",
            "label": "Census Block Group identifier",
            "universe": "Census Block Groups",
            "year": 2020,
        }
    ]
    if not result.error:
        columns.extend(
            {
                "column_name": row.get("COLUMN_NAME") or row.get("column_name"),
                "data_type": "NUMBER",
                "concept": row.get("CONCEPT") or row.get("concept"),
                "label": row.get("LABEL") or row.get("label"),
                "universe": row.get("UNIVERSE") or row.get("universe"),
                "year": row.get("YEAR") or row.get("year") or 2020,
            }
            for row in result.rows
        )
    return {
        "table_name": table,
        "description": "ACS 2020 Census Block Group estimate table discovered from Snowflake metadata",
        "geography_grain": "Census Block Group",
        "geography_column": "CENSUS_BLOCK_GROUP",
        "columns": columns,
        "error": result.error,
    }


def inspect_sample_rows(table_name: str, columns: list[str], limit: int = 5) -> dict[str, Any]:
    table = table_name.upper()
    if not _is_allowed_table_name(table):
        return {"error": "Table is outside the retrieved Census metadata scope."}
    allowed_columns = {column["column_name"].upper() for column in describe_table(table).get("columns", [])}
    requested = [column for column in columns if column.upper() in allowed_columns][:12]
    if not requested:
        return {"error": "No approved columns were requested."}
    safe_limit = max(1, min(limit, 10))
    quoted_columns = ", ".join(f'"{column}"' for column in requested)
    sql = f'SELECT {quoted_columns} FROM "{settings.snowflake_database}"."{settings.snowflake_schema}"."{table}" LIMIT {safe_limit}'
    result = SnowflakeQueryExecutor().execute(sql, {})
    return {"rows": result.rows, "columns": result.columns, "error": result.error}


def lookup_geography(query: str) -> dict[str, Any]:
    geographies = find_geographies(query)
    if geographies:
        geo = geographies[0]
        return {
            "resolved": True,
            "name": geo.name,
            "type": geo.type,
            "state_fips": geo.fips_code,
            "county_fips": geo.county_fips,
        }
    if query.strip().lower() in {"us", "usa", "united states", "united states overall"}:
        return {"resolved": True, "name": "United States", "type": "country", "state_fips": None}
    return {"resolved": False, "candidates": list(load_states().keys())[:10]}


def execute_sql(sql: str, parameters: dict | None = None) -> QueryResult:
    return SnowflakeQueryExecutor().execute(sql, parameters or {})


def enrich_geography_names(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    states = {meta["state_fips"]: name for name, meta in load_states().items()}
    enriched = []
    for row in rows:
        item = dict(row)
        state_fips = item.get("STATE_FIPS") or item.get("state_fips")
        if state_fips is not None and "STATE_NAME" not in item:
            item["STATE_NAME"] = states.get(str(state_fips), str(state_fips))
        enriched.append(item)
    return enriched


def _metadata_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "table_name": row.get("TABLE_NAME") or row.get("table_name"),
        "column_name": row.get("COLUMN_NAME") or row.get("column_name"),
        "data_type": row.get("DATA_TYPE") or row.get("data_type"),
        "concept": row.get("CONCEPT") or row.get("concept"),
        "label": row.get("LABEL") or row.get("label"),
        "universe": row.get("UNIVERSE") or row.get("universe"),
        "year": row.get("YEAR") or row.get("year") or 2020,
        "category": row.get("CATEGORY") or row.get("category"),
        "geography_grain": "Census Block Group",
        "geography_column": "CENSUS_BLOCK_GROUP",
    }


def _looks_like_land_or_geography(query: str) -> bool:
    lowered = query.lower()
    return any(term in lowered for term in ["land", "area", "water", "geography", "geographic", "block group", "cbg"])


def _column_matches_query(column: str, label: str, query: str) -> bool:
    words = set(re.findall(r"[a-z0-9]+", query.lower()))
    haystack = f"{column} {label}".lower()
    return any(word in haystack for word in words)


def _is_census_data_table(table: str) -> bool:
    return bool(TABLE_NAME_PATTERN.match(table))


def _is_allowed_table_name(table: str) -> bool:
    return table == GEOGRAPHY_TABLE or _is_census_data_table(table)


def _dedupe_metadata_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    deduped = []
    for row in rows:
        key = (str(row.get("table_name") or "").upper(), str(row.get("column_name") or "").upper())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped
