from __future__ import annotations

import re

from app.catalog.catalog_search import rank_schema_rows, schema_search_terms
from app.config import settings
from app.database.query_executor import SnowflakeQueryExecutor
from app.models.response_models import QueryResult


def load_columns_metadata() -> QueryResult:
    sql = """
SELECT
    table_catalog,
    table_schema,
    table_name,
    ordinal_position,
    column_name,
    data_type,
    comment
FROM US_OPEN_CENSUS_DATA__NEIGHBORHOOD_INSIGHTS__FREE_DATASET.INFORMATION_SCHEMA.COLUMNS
ORDER BY table_schema, table_name, ordinal_position
""".strip()
    return SnowflakeQueryExecutor().execute(sql, {})


def search_columns_metadata(text: str, limit: int = 40) -> QueryResult:
    terms = schema_search_terms(text)
    if not terms:
        return QueryResult(rows=[], columns=["TABLE_NAME", "COLUMN_NAME", "DATA_TYPE", "COMMENT"])
    predicates = []
    parameters: dict[str, str] = {}
    for index, term in enumerate(terms):
        key = f"term_{index}"
        parameters[key] = f"%{term}%"
        predicates.append(
            f"""(
                table_name ILIKE %({key})s
                OR column_name ILIKE %({key})s
                OR COALESCE(comment, '') ILIKE %({key})s
            )"""
        )
    sql = f"""
SELECT
    table_name,
    column_name,
    data_type,
    comment
FROM {settings.snowflake_database}.INFORMATION_SCHEMA.COLUMNS
WHERE table_schema = 'PUBLIC'
  AND ({' OR '.join(predicates)})
ORDER BY table_name, ordinal_position
LIMIT {max(1, min(limit * 4, 200))}
""".strip()
    result = SnowflakeQueryExecutor().execute(sql, parameters)
    if result.error:
        return result
    ranked_rows = rank_schema_rows(text, result.rows, limit=limit)
    return QueryResult(
        rows=ranked_rows,
        columns=result.columns,
        query_duration_ms=result.query_duration_ms,
        query_id=result.query_id,
    )


def search_variable_metadata(text: str, year: int = 2020, limit: int = 60) -> QueryResult:
    terms = schema_search_terms(text)
    if not terms:
        return QueryResult(rows=[], columns=[])
    metadata_table = f"{year}_METADATA_CBG_FIELD_DESCRIPTIONS"
    predicates = []
    parameters: dict[str, str] = {}
    for index, term in enumerate(terms):
        key = f"term_{index}"
        parameters[key] = f"%{term}%"
        predicates.append(
            f"""(
                descriptions.table_id ILIKE %({key})s
                OR descriptions.table_number ILIKE %({key})s
                OR descriptions.table_title ILIKE %({key})s
                OR descriptions.table_topics ILIKE %({key})s
                OR descriptions.table_universe ILIKE %({key})s
                OR COALESCE(descriptions.field_level_1, '') ILIKE %({key})s
                OR COALESCE(descriptions.field_level_2, '') ILIKE %({key})s
                OR COALESCE(descriptions.field_level_3, '') ILIKE %({key})s
                OR COALESCE(descriptions.field_level_4, '') ILIKE %({key})s
                OR COALESCE(descriptions.field_level_5, '') ILIKE %({key})s
                OR COALESCE(descriptions.field_level_6, '') ILIKE %({key})s
                OR COALESCE(descriptions.field_level_7, '') ILIKE %({key})s
                OR COALESCE(descriptions.field_level_8, '') ILIKE %({key})s
                OR COALESCE(descriptions."FIELD_LEVELl_9", '') ILIKE %({key})s
                OR COALESCE(descriptions.field_level_10, '') ILIKE %({key})s
            )"""
        )
    sql = f"""
WITH descriptions AS (
    SELECT
        table_id,
        table_number,
        table_title,
        table_topics,
        table_universe,
        field_level_1,
        field_level_2,
        field_level_3,
        field_level_4,
        field_level_5,
        field_level_6,
        field_level_7,
        field_level_8,
        "FIELD_LEVELl_9",
        field_level_10,
        '{year}_CBG_' || SUBSTR(table_number, 1, 3) AS data_table_name
    FROM {settings.snowflake_database}.PUBLIC."{metadata_table}"
)
SELECT
    descriptions.data_table_name AS table_name,
    descriptions.table_id AS column_name,
    columns.data_type AS data_type,
    descriptions.table_title AS concept,
    ARRAY_TO_STRING(
        ARRAY_CONSTRUCT_COMPACT(
            descriptions.field_level_1,
            descriptions.field_level_2,
            descriptions.field_level_3,
            descriptions.field_level_4,
            descriptions.field_level_5,
            descriptions.field_level_6,
            descriptions.field_level_7,
            descriptions.field_level_8,
            descriptions."FIELD_LEVELl_9",
            descriptions.field_level_10
        ),
        ': '
    ) AS label,
    descriptions.table_universe AS universe,
    descriptions.table_topics AS category,
    {year} AS year,
    IFF(REGEXP_LIKE(descriptions.table_id, '.*e[0-9]+$', 'i'), TRUE, FALSE) AS is_estimate,
    IFF(REGEXP_LIKE(descriptions.table_id, '.*m[0-9]+$', 'i'), TRUE, FALSE) AS is_margin_of_error,
    'CENSUS_BLOCK_GROUP' AS geography_column,
    descriptions.table_number AS table_number
FROM descriptions
JOIN {settings.snowflake_database}.INFORMATION_SCHEMA.COLUMNS columns
  ON columns.table_schema = 'PUBLIC'
 AND columns.table_name = descriptions.data_table_name
 AND UPPER(columns.column_name) = UPPER(descriptions.table_id)
WHERE ({' OR '.join(predicates)})
ORDER BY descriptions.data_table_name, descriptions.table_id
LIMIT {max(1, min(limit * 80, 5000))}
""".strip()
    result = SnowflakeQueryExecutor().execute(sql, parameters)
    if result.error:
        return result
    ranked_rows = _rank_variable_rows(text, result.rows, limit=limit)
    return QueryResult(
        rows=ranked_rows,
        columns=result.columns,
        query_duration_ms=result.query_duration_ms,
        query_id=result.query_id,
    )


def _rank_variable_rows(text: str, rows: list[dict], limit: int) -> list[dict]:
    terms = schema_search_terms(text)
    scored: list[tuple[int, dict]] = []
    for row in rows:
        label = str(row.get("LABEL") or row.get("label") or "")
        concept = str(row.get("CONCEPT") or row.get("concept") or "")
        universe = str(row.get("UNIVERSE") or row.get("universe") or "")
        category = str(row.get("CATEGORY") or row.get("category") or "")
        haystack = " ".join([label, concept, universe, category, str(row.get("COLUMN_NAME") or "")]).lower()
        label_tokens = _metadata_tokens(label)
        concept_tokens = _metadata_tokens(concept)
        universe_tokens = _metadata_tokens(universe)
        category_tokens = _metadata_tokens(category)
        haystack_tokens = _metadata_tokens(haystack)
        score = sum(8 for term in terms if term in label_tokens)
        score += sum(5 for term in terms if term in concept_tokens or term in category_tokens)
        score += sum(3 for term in terms if term in universe_tokens)
        score += sum(1 for term in terms if term in haystack_tokens)
        score += sum(4 for term in terms if f" {term} " in f" {haystack} ")
        score += _semantic_metadata_bonus(text, label, concept, universe, category)
        if str(row.get("IS_MARGIN_OF_ERROR")).lower() == "true":
            score -= 20
        if score > 0:
            enriched = dict(row)
            enriched["SCORE"] = score
            scored.append((score, enriched))
    return [row for _, row in sorted(scored, key=lambda item: item[0], reverse=True)[:limit]]


def _metadata_tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _semantic_metadata_bonus(query: str, label: str, concept: str, universe: str, category: str) -> int:
    query_lower = query.lower()
    label_lower = label.lower()
    combined = " ".join([label, concept, universe, category]).lower()
    bonus = 0

    asks_for_units = any(term in query_lower for term in ["unit", "units", "housing"])
    asks_for_renters = any(term in query_lower for term in ["rental", "rentals", "renter", "renters"])
    asks_for_count = asks_for_units and not any(term in query_lower for term in ["median", "average", "aggregate", "dollar", "cost", "gross rent"])

    if asks_for_renters and "renter occupied" in combined:
        bonus += 18
    if asks_for_renters and "tenure" in combined:
        bonus += 16
    if asks_for_renters and label_lower.startswith("estimate: tenure:"):
        bonus += 30
    if asks_for_renters and "estimate: tenure (" in label_lower:
        bonus -= 10
    if asks_for_renters and "tenure by" in label_lower:
        bonus -= 6
    if asks_for_units and "housing units" in combined:
        bonus += 10
    if asks_for_count and "total: renter occupied" in label_lower:
        bonus += 14
    if asks_for_count and any(term in label_lower for term in ["median", "average", "aggregate", "dollars", "gross rent"]):
        bonus -= 24
    if asks_for_units and "total population" in label_lower:
        bonus -= 16

    return bonus
