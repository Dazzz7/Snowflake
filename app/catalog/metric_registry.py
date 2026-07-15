from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from app.models.query_models import MetricDefinition


ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "metadata" / "verified_metrics.json"
VARIABLE_CATALOG_PATH = ROOT / "metadata" / "variable_catalog.json"
TAXONOMY_PATH = ROOT / "metadata" / "taxonomy.json"
METRIC_MATCH_STOPWORDS = {
    "block",
    "census",
    "group",
    "groups",
    "over",
    "under",
    "which",
    "what",
    "have",
    "with",
}


@lru_cache
def load_metrics() -> dict[str, MetricDefinition]:
    raw = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    return {
        metric_id: MetricDefinition(metric_id=metric_id, **definition)
        for metric_id, definition in raw.items()
    }


def resolve_metric(text: str | None) -> MetricDefinition | None:
    if not text:
        return None
    normalized = text.lower().strip()
    normalized_tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", normalized.replace("_", " "))
        if token not in METRIC_MATCH_STOPWORDS
    ]
    metrics = load_metrics()
    if normalized in metrics:
        return metrics[normalized]
    scored: list[tuple[int, MetricDefinition]] = []
    for metric in metrics.values():
        candidates = [metric.display_name, metric.description, metric.metric_id, *metric.synonyms]
        score = 0
        for candidate in candidates:
            candidate_lower = candidate.lower()
            if candidate_lower == normalized:
                score = max(score, 100)
            elif candidate_lower in normalized:
                score = max(score, 80 + len(candidate_lower.split()))
            elif normalized in candidate_lower:
                score = max(score, 50)
            else:
                words = {
                    word
                    for word in re.findall(r"[a-z0-9]+", candidate_lower.replace("_", " "))
                    if len(word) > 2 and word not in METRIC_MATCH_STOPWORDS
                }
                score = max(score, len(words.intersection(normalized_tokens)))
        if score:
            scored.append((score, metric))
    if scored:
        return sorted(scored, key=lambda item: item[0], reverse=True)[0][1]
    return None


@lru_cache
def load_variable_catalog() -> list[dict]:
    if not VARIABLE_CATALOG_PATH.exists():
        return []
    return json.loads(VARIABLE_CATALOG_PATH.read_text(encoding="utf-8"))


@lru_cache
def load_taxonomy() -> dict:
    return json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))


def search_variable_catalog(text: str, limit: int = 5) -> list[dict]:
    normalized_words = {word for word in text.lower().replace("_", " ").split() if len(word) > 2}
    scored: list[tuple[int, dict]] = []
    for row in load_variable_catalog():
        haystack = " ".join(
            [
                row.get("variable_id", ""),
                row.get("concept", ""),
                row.get("label", ""),
                row.get("universe", ""),
                row.get("category", ""),
                row.get("subcategory", ""),
                " ".join(row.get("synonyms", [])),
            ]
        ).lower()
        score = sum(1 for word in normalized_words if word in haystack)
        if score:
            scored.append((score, row))
    return [row for _, row in sorted(scored, key=lambda item: item[0], reverse=True)[:limit]]
