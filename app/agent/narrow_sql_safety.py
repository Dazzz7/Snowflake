from __future__ import annotations

import re

from app.config import settings
from app.models.query_models import ValidationResult


BLOCKED_SQL_KEYWORDS = {
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "create",
    "truncate",
    "merge",
    "copy",
    "put",
    "get",
    "call",
    "grant",
    "revoke",
}

APPROVED_TABLES = {
    "2020_CBG_B01",
    "2020_CBG_B02",
    "2020_METADATA_CBG_GEOGRAPHIC_DATA",
}

APPROVED_COLUMNS = {
    "CENSUS_BLOCK_GROUP",
    "B01003e1",
    "AMOUNT_LAND",
    "AMOUNT_WATER",
    "LATITUDE",
    "LONGITUDE",
    *{f"B01001e{index}" for index in range(1, 50)},
    *{f"B02001e{index}" for index in range(1, 11)},
}


def normalize_snowflake_identifiers(
    sql: str,
    approved_tables: set[str] | None = None,
    approved_columns: set[str] | None = None,
) -> str:
    normalized = sql
    database = settings.snowflake_database
    schema = settings.snowflake_schema
    tables = {table.upper() for table in (approved_tables or APPROVED_TABLES)}
    columns = approved_columns or APPROVED_COLUMNS

    for table in sorted(tables, key=len, reverse=True):
        quoted_table = f'"{database}"."{schema}"."{table}"'
        patterns = [
            rf'(?<!")\b{re.escape(database)}\s*\.\s*{re.escape(schema)}\s*\.\s*{re.escape(table)}\b(?!")',
            rf'(?<!")\b{re.escape(schema)}\s*\.\s*{re.escape(table)}\b(?!")',
            rf'(?<!")\b{re.escape(table)}\b(?!")',
        ]
        for pattern in patterns:
            normalized = re.sub(pattern, quoted_table, normalized, flags=re.IGNORECASE)

    for column in sorted(columns, key=len, reverse=True):
        normalized = re.sub(
            rf'(?<!")\b{re.escape(column)}\b(?!")',
            f'"{column}"',
            normalized,
            flags=re.IGNORECASE,
        )
    return normalized


def validate_narrow_sql(
    sql: str,
    approved_tables: set[str] | None = None,
    approved_columns: set[str] | None = None,
) -> ValidationResult:
    stripped = sql.strip()
    lowered = stripped.lower()
    tables = {table.upper() for table in (approved_tables or APPROVED_TABLES)}
    columns = {column.upper() for column in (approved_columns or APPROVED_COLUMNS)}
    if not stripped:
        return ValidationResult(False, "No SQL was generated.")
    if not (lowered.startswith("select") or lowered.startswith("with")):
        return ValidationResult(False, "Only SELECT statements are allowed.")
    if any(re.search(rf"\b{keyword}\b", lowered) for keyword in BLOCKED_SQL_KEYWORDS):
        return ValidationResult(False, "The query contains a blocked SQL operation.")
    if ";" in stripped.rstrip(";"):
        return ValidationResult(False, "Only one SQL statement is allowed.")
    if settings.snowflake_database.lower() not in lowered:
        return ValidationResult(False, "The query must use the approved Census database.")
    if "information_schema" in lowered or "account_usage" in lowered:
        return ValidationResult(False, "The query may not access account or schema metadata.")

    table_refs = _referenced_tables(stripped)
    if not table_refs:
        return ValidationResult(False, "The query must reference at least one approved Census table.")
    unauthorized = {table for table in table_refs if table.upper() not in tables}
    if unauthorized:
        return ValidationResult(False, f"The query references tables outside the retrieved metadata: {', '.join(sorted(unauthorized))}.")

    unauthorized_columns = _referenced_census_columns(stripped, columns, tables)
    if unauthorized_columns:
        return ValidationResult(False, f"The query references columns outside the retrieved metadata: {', '.join(sorted(unauthorized_columns))}.")
    return ValidationResult(True)


def enforce_row_limit(sql: str, limit: int = 500) -> str:
    stripped = sql.strip().rstrip(";")
    if re.search(r"\blimit\s+\d+\b", stripped, re.IGNORECASE):
        return stripped
    return f"{stripped}\nLIMIT {limit}"


def _referenced_tables(sql: str) -> set[str]:
    refs: set[str] = set()
    for match in re.finditer(r'"([^"]+)"\."([^"]+)"\."([^"]+)"', sql):
        table = match.group(3)
        if _looks_like_census_table(table):
            refs.add(table.upper())
    for match in re.finditer(r"\b(?:from|join)\s+([A-Za-z0-9_\.]+)", sql, re.IGNORECASE):
        table = match.group(1).split(".")[-1].strip('"')
        if _looks_like_census_table(table):
            refs.add(table.upper())
    for match in re.finditer(r'"([^"]+)"', sql):
        identifier = match.group(1)
        if _looks_like_census_table(identifier):
            refs.add(identifier.upper())
    return refs


def _referenced_census_columns(sql: str, approved_columns: set[str], approved_tables: set[str]) -> set[str]:
    unauthorized: set[str] = set()
    allowed_non_metric = {
        settings.snowflake_database.upper(),
        settings.snowflake_schema.upper(),
        *approved_tables,
    }
    for identifier in re.findall(r'"([^"]+)"', sql):
        upper = identifier.upper()
        if upper in allowed_non_metric or upper in approved_columns:
            continue
        if _looks_like_census_column(identifier):
            unauthorized.add(identifier)
    for token in re.findall(r"\b[A-Z][0-9]{5}[A-Z]?[EM][0-9]+\b", sql, re.IGNORECASE):
        if token.upper() not in approved_columns:
            unauthorized.add(token)
    for token in ["CENSUS_BLOCK_GROUP", "AMOUNT_LAND", "AMOUNT_WATER", "LATITUDE", "LONGITUDE"]:
        if re.search(rf"(?<![\w\"]){token}(?![\w\"])", sql, re.IGNORECASE) and token.upper() not in approved_columns:
            unauthorized.add(token)
    return unauthorized


def _looks_like_census_table(identifier: str) -> bool:
    upper = identifier.upper()
    return bool(re.match(r"^2020_CBG_[A-Z0-9]{3}$", upper)) or upper == "2020_METADATA_CBG_GEOGRAPHIC_DATA"


def _looks_like_census_column(identifier: str) -> bool:
    upper = identifier.upper()
    return bool(re.match(r"^[A-Z][0-9]{5}[A-Z]?[EM][0-9]+$", upper)) or upper in {
        "CENSUS_BLOCK_GROUP",
        "AMOUNT_LAND",
        "AMOUNT_WATER",
        "LATITUDE",
        "LONGITUDE",
    }
