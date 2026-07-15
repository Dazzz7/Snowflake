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
        rewritten_question = None
        if self.llm:
            rewritten_question = self._rewrite_with_llm(question)
        deterministic = self._parse_deterministically(rewritten_question or question)
        if self.llm:
            deterministic.llm_attempted = True
            deterministic.llm_provider = settings.llm_model
            if rewritten_question:
                deterministic.llm_succeeded = True
            llm_intent = None if rewritten_question and not deterministic.needs_clarification else self._parse_with_llm(question)
            if llm_intent:
                deterministic.llm_succeeded = True
                if deterministic.intent == "unsupported" and llm_intent.metric in load_metrics():
                    deterministic.metric = llm_intent.metric
                    deterministic.needs_clarification = bool(llm_intent.needs_clarification)
                    deterministic.clarification_question = llm_intent.clarification_question
                    deterministic.intent = (
                        llm_intent.intent
                        if llm_intent.intent in {"aggregate_metric", "comparison", "ranking"}
                        else deterministic.intent
                    )
        if deterministic.needs_clarification:
            return deterministic
        if not deterministic.needs_clarification and deterministic.intent != "unsupported":
            return deterministic
        return deterministic

    def _rewrite_with_llm(self, question: str) -> str | None:
        if not self.llm:
            return None
        system = (
            "Rewrite the user's Census analytics question as one clear, literal question. "
            "Preserve all named geographies, metric words, age ranges, thresholds, ranking direction, and requested limits. "
            "Do not answer the question. Do not add facts. Return strict JSON only."
        )
        payload = self.llm.generate_json(
            system,
            (
                f"Question: {question}\n"
                'Return keys: rewritten_question. Example: "Which state has the less people age 55 and older?" '
                '=> "Which state has the fewest people age 55 and older?"'
            ),
        )
        if not payload:
            return None
        rewritten = str(payload.get("rewritten_question") or "").strip()
        if not rewritten or len(rewritten) > 300:
            return None
        return rewritten

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
        age_min, age_max = self._age_range_from_text(lowered)
        value_kind = "percentage" if re.search(r"\b(percentage|percent|share|rate)\b", lowered) else "count"
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
        if age_min is not None or age_max is not None:
            dimension = "age"
            metric = "population_by_age"
            if threshold_value in {age_min, age_max, (age_max + 1 if age_max is not None else None)}:
                threshold_operator = None
                threshold_value = None
        elif dimension == "age":
            metric = "population_by_age"
        if dimension == "race":
            metric = "population_by_race"

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
        if metric == "population_by_age" and geographies and age_min is None and age_max is None:
            intent = "breakdown"
            operation_type = "breakdown"
        elif metric == "population_by_race" and geographies:
            intent = "breakdown"
            operation_type = "breakdown"
        elif threshold_operator and geography_level:
            intent = "filter"
            operation_type = "threshold"
        elif rank:
            intent = "ranking"
            operation_type = "rank"
            limit = rank
        elif any(
            term in lowered
            for term in [
                "top",
                "largest",
                "highest",
                "rank",
                "higher",
                "most",
                "lowest",
                "smallest",
                "least",
                "fewest",
                "less people",
                "fewer people",
                "lower",
                "more no",
                "more number",
            ]
        ):
            intent = "ranking"
            operation_type = "maximum"
            if any(term in lowered for term in ["lowest", "smallest", "least", "fewest", "less people", "fewer people", "lower"]):
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
            age_min=age_min,
            age_max=age_max,
            value_kind=value_kind if dimension == "age" and (age_min is not None or age_max is not None) else None,
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

    def _age_range_from_text(self, lowered: str) -> tuple[int | None, int | None]:
        plus_match = re.search(r"\b(\d{1,3})\s*\+\b", lowered)
        if plus_match:
            return int(plus_match.group(1)), None

        older_match = re.search(
            r"\b(?:age|ages|aged|people age|residents age)?\s*(\d{1,3})\s*(?:and older|or older|and over|or over|plus)\b",
            lowered,
        )
        if older_match:
            return int(older_match.group(1)), None

        over_match = re.search(r"\b(?:over|older than|greater than|above)\s+(\d{1,3})\b", lowered)
        if over_match and re.search(r"\b(age|ages|older|residents|people|population|percent|percentage|share)\b", lowered):
            return int(over_match.group(1)), None

        under_match = re.search(r"\b(?:under|younger than|less than|below)\s+(\d{1,3})\b", lowered)
        if under_match and re.search(r"\b(age|ages|younger|residents|people|population|percent|percentage|share)\b", lowered):
            return None, int(under_match.group(1)) - 1

        range_match = re.search(r"\b(?:age|ages|aged)?\s*(\d{1,3})\s*(?:to|-)\s*(\d{1,3})\b", lowered)
        if range_match and re.search(r"\b(age|ages|aged|residents|people|population)\b", lowered):
            low = int(range_match.group(1))
            high = int(range_match.group(2))
            return min(low, high), max(low, high)

        if re.search(r"\b(senior|seniors|elderly|older adults|old people)\b", lowered):
            return 65, None

        return None, None

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
