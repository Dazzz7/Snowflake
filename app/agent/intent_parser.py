from __future__ import annotations

import re

from app.agent.hosted_llm_client import HostedLLMClient
from app.catalog.geography import find_geographies
from app.catalog.metric_registry import load_metrics
from app.catalog.metric_registry import resolve_metric
from app.config import settings
from app.models.intent_models import QueryIntent


NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


class IntentParser:
    def __init__(self, llm: HostedLLMClient | None = None) -> None:
        self.llm = llm if llm is not None else (HostedLLMClient() if settings.has_hosted_llm_config else None)

    def parse(self, question: str) -> QueryIntent:
        deterministic = self._parse_deterministically(question)
        if deterministic.needs_clarification:
            return deterministic
        if not deterministic.needs_clarification and deterministic.intent != "unsupported":
            return deterministic
        if not self.llm:
            return deterministic
        llm_intent = self._parse_with_llm(question)
        if llm_intent and llm_intent.metric:
            deterministic.metric = llm_intent.metric
            deterministic.needs_clarification = False
            deterministic.clarification_question = None
            deterministic.intent = llm_intent.intent if llm_intent.intent in {"aggregate_metric", "comparison", "ranking"} else deterministic.intent
        return deterministic

    def _parse_with_llm(self, question: str) -> QueryIntent | None:
        allowed_metrics = ", ".join(sorted(load_metrics()))
        system = (
            "Extract Census analytics intent as strict JSON only. Allowed intents: "
            "aggregate_metric, comparison, ranking, unsupported, ambiguous. "
            f"Allowed metrics: {allowed_metrics}, null. "
            "Do not invent geographies or facts."
        )
        if not self.llm:
            return None
        payload = self.llm.generate_json(
            system,
            f"Question: {question}\nReturn keys: intent, metric, year, aggregation, needs_clarification, clarification_question.",
        )
        if not payload:
            return None
        return QueryIntent(
            intent=str(payload.get("intent") or "unsupported"),
            metric=payload.get("metric"),
            year=payload.get("year"),
            aggregation=payload.get("aggregation"),
            needs_clarification=bool(payload.get("needs_clarification", False)),
            clarification_question=payload.get("clarification_question"),
        )

    def _parse_deterministically(self, question: str) -> QueryIntent:
        lowered = question.lower()
        geographies = find_geographies(question)
        metric = self._metric_from_text(lowered)
        geography_level = self._geography_level_from_text(lowered, geographies)
        geography_scope = "selected" if geographies else ("all" if geography_level else None)
        year_match = re.search(r"\b(20\d{2}|19\d{2})\b", question)
        year = int(year_match.group(1)) if year_match else None
        operation_type = None
        sort_direction = "descending"
        limit = self._limit_from_text(lowered)
        rank = self._rank_from_text(lowered)
        threshold_operator, threshold_value = self._threshold_from_text(lowered)
        dimension = None
        if re.search(r"\b(age|age distribution|by age)\b", lowered):
            dimension = "age"
        if re.search(r"\b(race|racial|by race)\b", lowered):
            dimension = "race"
        if re.search(r"\bincome\b", lowered) and not re.search(r"\b(median household income|median income|per capita|family income|mean income)\b", lowered):
            return QueryIntent(
                intent="ambiguous",
                geographies=geographies,
                geography_level=geography_level,
                geography_scope=geography_scope,
                year=year,
                needs_clarification=True,
                clarification_question="Do you mean median household income, per-capita income, family income, or another income measure?",
            )
        has_65_plus_language = re.search(r"(65\+|65 and older|older than 65|greater than 65\s+age|over 65|senior|elderly|old people)", lowered)
        if dimension == "age" and not has_65_plus_language:
            metric = "population_by_age"
        if dimension == "race":
            metric = "population_by_race"
        if has_65_plus_language:
            if "percentage" in lowered or "percent" in lowered or "share" in lowered:
                metric = "population_65_plus_percentage"
            else:
                metric = "population_65_plus"
            dimension = "age"
            if threshold_value == 65:
                threshold_operator = None
                threshold_value = None

        if not metric:
            return QueryIntent(
                intent="ambiguous",
                geographies=geographies,
                geography_level=geography_level,
                geography_scope=geography_scope,
                year=year,
                needs_clarification=True,
                clarification_question="Which Census measure do you mean: total population, households, or median household income?",
            )
        intent = "aggregate_metric"
        if metric in {"population_by_age", "population_by_race"} and geographies:
            intent = "breakdown"
            operation_type = "breakdown"
        elif threshold_operator and geography_level:
            intent = "filter"
            operation_type = "threshold"
        elif rank:
            intent = "ranking"
            operation_type = "rank"
            limit = rank
        elif any(term in lowered for term in ["top", "largest", "highest", "rank", "higher", "most", "lowest", "smallest", "more no", "more number"]):
            intent = "ranking"
            operation_type = "maximum"
            if any(term in lowered for term in ["lowest", "smallest"]):
                sort_direction = "ascending"
                operation_type = "minimum"
            limit = limit or 1
        elif any(term in lowered for term in ["compare", "versus", " vs ", "larger", "which one", "more people", "has more"]):
            intent = "comparison"
            operation_type = "comparison"

        if not geographies and intent == "aggregate_metric":
            return QueryIntent(
                intent="ambiguous",
                metric=metric,
                geography_level=geography_level,
                geography_scope=geography_scope,
                year=year,
                needs_clarification=True,
                clarification_question="Which geography should I use: the United States, a state, a county, or another geography?",
            )
        if intent in {"ranking", "filter"} and not geography_level:
            return QueryIntent(
                intent="ambiguous",
                metric=metric,
                year=year,
                needs_clarification=True,
                clarification_question="Would you like me to rank states, counties, tracts, or block groups?",
            )

        return QueryIntent(
            intent=intent,
            metric=metric,
            geographies=geographies,
            geography_level=geography_level,
            geography_scope=geography_scope,
            year=year,
            aggregation="total",
            operation_type=operation_type,
            sort_direction=sort_direction,
            limit=limit,
            rank=rank,
            threshold_operator=threshold_operator,
            threshold_value=threshold_value,
            dimension=dimension,
        )

    def _metric_from_text(self, lowered: str) -> str | None:
        if resolve_metric(lowered):
            return resolve_metric(lowered).metric_id
        if "resident" in lowered or "people" in lowered:
            return "total_population"
        return None

    def _geography_level_from_text(self, lowered: str, geographies: list) -> str | None:
        if "county" in lowered or "counties" in lowered:
            return "county"
        if "state" in lowered or "states" in lowered or "usa" in lowered or "u.s." in lowered or "us " in lowered:
            return "state"
        if "tract" in lowered:
            return "tract"
        if "block group" in lowered:
            return "block_group"
        if geographies:
            return geographies[0].type
        return None

    def _limit_from_text(self, lowered: str) -> int | None:
        match = re.search(r"\btop\s+(\d+)\b", lowered)
        if match:
            return int(match.group(1))
        for word, value in NUMBER_WORDS.items():
            if re.search(rf"\btop\s+{word}\b", lowered):
                return value
        return None

    def _rank_from_text(self, lowered: str) -> int | None:
        match = re.search(r"\brank\s+(\d+)\b", lowered)
        if match:
            return int(match.group(1))
        ordinals = {
            "first": 1,
            "second": 2,
            "third": 3,
            "fourth": 4,
            "fifth": 5,
            "sixth": 6,
            "seventh": 7,
            "eighth": 8,
            "ninth": 9,
            "tenth": 10,
        }
        for word, value in ordinals.items():
            if re.search(rf"\b{word}\b", lowered):
                return value
        return None

    def _threshold_from_text(self, lowered: str) -> tuple[str | None, float | None]:
        match = re.search(r"\b(more than|over|above|greater than)\s+\$?([\d,.]+)\s*(million|m)?\b", lowered)
        if match:
            value = float(match.group(2).replace(",", ""))
            if match.group(3):
                value *= 1_000_000
            return ">", value
        match = re.search(r"\b(less than|under|below|fewer than)\s+\$?([\d,.]+)\s*(million|m)?\b", lowered)
        if match:
            value = float(match.group(2).replace(",", ""))
            if match.group(3):
                value *= 1_000_000
            return "<", value
        return None, None
