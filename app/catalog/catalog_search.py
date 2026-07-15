from __future__ import annotations

import re

from app.catalog.metric_registry import resolve_metric
from app.models.query_models import MetricDefinition


STOPWORDS = {
    "about",
    "answer",
    "available",
    "columns",
    "data",
    "dataset",
    "field",
    "fields",
    "have",
    "kind",
    "metadata",
    "show",
    "table",
    "tables",
    "what",
    "which",
    "with",
}


def search_metric_catalog(text: str) -> MetricDefinition | None:
    return resolve_metric(text)


def schema_search_terms(text: str) -> list[str]:
    terms = []
    for token in re.findall(r"[a-zA-Z0-9_]+", text.lower()):
        if len(token) < 3 or token in STOPWORDS:
            continue
        if token not in terms:
            terms.append(token)
    return terms[:8]


def rank_schema_rows(text: str, rows: list[dict], limit: int = 20) -> list[dict]:
    terms = schema_search_terms(text)
    scored: list[tuple[int, dict]] = []
    for row in rows:
        haystack_parts = [
            str(row.get("TABLE_NAME") or row.get("table_name") or ""),
            str(row.get("COLUMN_NAME") or row.get("column_name") or ""),
            str(row.get("DATA_TYPE") or row.get("data_type") or ""),
            str(row.get("COMMENT") or row.get("comment") or ""),
        ]
        haystack = " ".join(haystack_parts).lower()
        score = sum(4 for term in terms if term in str(row.get("COLUMN_NAME") or row.get("column_name") or "").lower())
        score += sum(2 for term in terms if term in str(row.get("TABLE_NAME") or row.get("table_name") or "").lower())
        score += sum(1 for term in terms if term in haystack)
        if score:
            scored.append((score, row))
    return [row for _, row in sorted(scored, key=lambda item: item[0], reverse=True)[:limit]]


def summarize_schema_matches(rows: list[dict], limit: int = 10) -> list[dict]:
    summary = []
    for row in rows[:limit]:
        summary.append(
            {
                "table": row.get("TABLE_NAME") or row.get("table_name"),
                "column": row.get("COLUMN_NAME") or row.get("column_name"),
                "type": row.get("DATA_TYPE") or row.get("data_type"),
                "comment": row.get("COMMENT") or row.get("comment"),
            }
        )
    return summary
