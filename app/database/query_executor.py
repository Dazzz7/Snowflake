from __future__ import annotations

import time
from decimal import Decimal

from app.config import settings
from app.database.snowflake_client import SnowflakeConnectionError, snowflake_connection
from app.models.response_models import QueryResult


def _json_safe(value: object) -> object:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


class SnowflakeQueryExecutor:
    def execute(self, sql: str, parameters: dict | None = None, timeout_seconds: int | None = None) -> QueryResult:
        started = time.perf_counter()
        parameters = parameters or {}
        try:
            with snowflake_connection() as conn:
                cursor = conn.cursor()
                try:
                    cursor.execute("ALTER SESSION SET QUERY_TAG = 'census_chat_agent'")
                    cursor.execute(f"ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = {timeout_seconds or settings.query_timeout_seconds}")
                    cursor.execute(sql, parameters)
                    columns = [column[0] for column in cursor.description or []]
                    rows = [
                        {columns[index]: _json_safe(value) for index, value in enumerate(record)}
                        for record in cursor.fetchall()
                    ]
                finally:
                    cursor.close()
        except SnowflakeConnectionError as exc:
            return QueryResult(error=str(exc))
        except Exception as exc:
            return QueryResult(error=f"I am having trouble querying the Census data: {exc}")
        duration = int((time.perf_counter() - started) * 1000)
        return QueryResult(rows=rows, columns=columns, query_duration_ms=duration)
