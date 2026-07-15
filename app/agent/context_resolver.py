from __future__ import annotations

import re

from app.catalog.geography import find_geographies, load_states
from app.memory.conversation_state import ConversationState


FOLLOW_UP_PATTERNS = [
    r"^\s*what about\b",
    r"^\s*how about\b",
    r"^\s*and\b",
    r"compare .*spoke",
    r"^\s*what is second\b",
    r"^\s*what's second\b",
    r"^\s*what is third\b",
    r"^\s*what's third\b",
    r"^\s*show me (the )?top\b",
    r"^\s*top\s+\d+\b",
    r"^\s*compare it with\b",
    r"^\s*compare them\b",
    r"which one is larger",
    r"which is larger",
]

ORDINAL_RANKS = {
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


def resolve_context(question: str, state: ConversationState) -> str:
    lowered = question.lower()
    is_follow_up = any(re.search(pattern, lowered) for pattern in FOLLOW_UP_PATTERNS)
    if not is_follow_up:
        return question

    geographies = find_geographies(question)
    if re.search(r"^\s*compare it with\b", lowered) and state.last_metric and state.last_result_set:
        state_lookup = {meta["state_fips"]: name for name, meta in load_states().items()}
        last_row = state.last_result_set[0]
        previous_name = last_row.get("GEOGRAPHY_NAME") or last_row.get("geography_name")
        fips = last_row.get("STATE_FIPS") or last_row.get("state_fips")
        if not previous_name and fips:
            previous_name = state_lookup.get(str(fips))
        explicit_names = [geo.name for geo in geographies if geo.name]
        names = [name for name in [previous_name, *explicit_names] if name]
        if len(names) >= 2:
            return f"Compare {state.last_metric} for {', '.join(dict.fromkeys(names))}"

    if re.search(r"^\s*compare it with\b", lowered) and state.last_metric and state.last_geographies:
        explicit_names = [geo.name for geo in geographies if geo.name]
        previous_name = state.last_geographies[-1].name
        names = [name for name in [previous_name, *explicit_names] if name]
        if len(names) >= 2:
            return f"Compare {state.last_metric} for {', '.join(dict.fromkeys(names))}"

    if re.search(r"^\s*compare them\b", lowered) and state.last_metric and len(state.last_geographies) >= 2:
        names = [geo.name for geo in state.last_geographies if geo.name]
        return f"Compare {state.last_metric} for {', '.join(dict.fromkeys(names))}"
    if re.search(r"compare .*other .*spoke|compare .*spoke", lowered) and state.last_metric:
        mentioned = [geo.name for geo in state.mentioned_geographies if geo.name]
        explicit = [geo.name for geo in geographies if geo.name]
        names = []
        for name in [*explicit, *mentioned]:
            if name and name not in names:
                names.append(name)
        if len(names) >= 2:
            return f"Compare {state.last_metric} for {', '.join(names)}"

    if re.search(r"^\s*(what about|how about)\b", lowered) and state.last_metric and geographies:
        geo_names = " and ".join(geo.name or "" for geo in geographies)
        return f"What is the {state.last_metric} of {geo_names}?"

    if state.last_metric:
        top_match = re.search(r"\btop\s+(\d+)\b", lowered)
        if top_match:
            level = state.last_geography_level if state.last_geography_level in {"state", "county"} else "state"
            return f"Show top {top_match.group(1)} {level}s by {state.last_metric}"
        for word, value in NUMBER_WORDS.items():
            if re.search(rf"\btop\s+{word}\b", lowered):
                level = state.last_geography_level if state.last_geography_level in {"state", "county"} else "state"
                return f"Show top {value} {level}s by {state.last_metric}"
        for word, rank in ORDINAL_RANKS.items():
            if re.search(rf"\b{word}\b", lowered):
                level = state.last_geography_level if state.last_geography_level in {"state", "county"} else "state"
                return f"Show rank {rank} {level} by {state.last_metric}"

    if "which one is larger" in lowered or "which is larger" in lowered:
        names = ", ".join(geo.name or "" for geo in state.last_geographies if geo.name)
        metric = state.last_metric or "the previous metric"
        if names:
            return f"Compare {metric} for {names}"

    if geographies and state.last_metric:
        geo_names = " and ".join(geo.name or "" for geo in geographies)
        return f"What is the {state.last_metric} of {geo_names}?"

    return question
