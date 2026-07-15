from __future__ import annotations

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
