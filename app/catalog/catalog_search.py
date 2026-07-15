from __future__ import annotations

from app.catalog.metric_registry import resolve_metric
from app.models.query_models import MetricDefinition


def search_metric_catalog(text: str) -> MetricDefinition | None:
    return resolve_metric(text)

