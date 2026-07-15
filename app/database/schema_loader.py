from __future__ import annotations

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

