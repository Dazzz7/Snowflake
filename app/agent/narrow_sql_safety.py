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


def validate_narrow_sql(sql: str) -> ValidationResult:
    stripped = sql.strip()
    lowered = stripped.lower()
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

    referenced_tables = set(re.findall(r'"([^"]+)"', stripped))
    table_refs = {item for item in referenced_tables if item.upper().startswith(("2020_CBG_", "2020_METADATA_"))}
    table_refs.update(
        match.upper()
        for match in re.findall(r"\b(?:from|join)\s+([A-Za-z0-9_]+)", stripped, re.IGNORECASE)
        if match.upper().startswith(("2020_CBG_", "2020_METADATA_"))
    )
    unauthorized = {table for table in table_refs if table.upper() not in APPROVED_TABLES}
    if unauthorized:
        return ValidationResult(False, f"The query references tables outside the narrowed scope: {', '.join(sorted(unauthorized))}.")
    return ValidationResult(True)


def enforce_row_limit(sql: str, limit: int = 500) -> str:
    stripped = sql.strip().rstrip(";")
    if re.search(r"\blimit\s+\d+\b", stripped, re.IGNORECASE):
        return stripped
    return f"{stripped}\nLIMIT {limit}"
