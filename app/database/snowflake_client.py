from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from app.config import settings


class SnowflakeConnectionError(RuntimeError):
    pass


@contextmanager
def snowflake_connection() -> Iterator[object]:
    if not settings.has_snowflake_credentials:
        raise SnowflakeConnectionError(
            "Snowflake credentials are not configured. Set SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, "
            "SNOWFLAKE_PASSWORD, and SNOWFLAKE_WAREHOUSE."
        )
    try:
        import snowflake.connector
    except ImportError as exc:
        raise SnowflakeConnectionError(
            "snowflake-connector-python is not installed. Install requirements.txt before connecting."
        ) from exc

    conn = snowflake.connector.connect(
        account=settings.snowflake_account,
        user=settings.snowflake_user,
        password=settings.snowflake_password,
        warehouse=settings.snowflake_warehouse,
        database=settings.snowflake_database,
        schema=settings.snowflake_schema,
        role=settings.snowflake_role,
        client_session_keep_alive=False,
        login_timeout=10,
        network_timeout=settings.query_timeout_seconds,
    )
    try:
        yield conn
    finally:
        conn.close()

