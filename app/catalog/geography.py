from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from app.models.intent_models import Geography


ROOT = Path(__file__).resolve().parents[2]
STATES_PATH = ROOT / "metadata" / "state_fips.json"
GEOGRAPHIES_PATH = ROOT / "metadata" / "geographies.json"
COUNTIES_PATH = ROOT / "metadata" / "county_fips.json"


@lru_cache
def load_states() -> dict[str, dict]:
    return json.loads(STATES_PATH.read_text(encoding="utf-8"))


@lru_cache
def load_named_geographies() -> dict[str, dict]:
    if not GEOGRAPHIES_PATH.exists():
        return {}
    return json.loads(GEOGRAPHIES_PATH.read_text(encoding="utf-8"))


@lru_cache
def load_counties() -> dict[str, str]:
    if not COUNTIES_PATH.exists():
        return {}
    return json.loads(COUNTIES_PATH.read_text(encoding="utf-8"))


def normalize_state_name(text: str) -> Geography | None:
    states = load_states()
    cleaned = re.sub(r"\bstate of\b", "", text, flags=re.IGNORECASE).strip(" ?.,")
    lowered = cleaned.lower()
    for name, meta in states.items():
        aliases = {name.lower(), meta["abbreviation"].lower(), *(alias.lower() for alias in meta.get("aliases", []))}
        if lowered in aliases:
            return Geography(type="state", name=name, fips_code=meta["state_fips"])
    for name, meta in states.items():
        aliases = [name, *meta.get("aliases", [])]
        abbreviation = meta["abbreviation"]
        if any(re.search(rf"\b{re.escape(alias)}\b", text, re.IGNORECASE) for alias in aliases):
            return Geography(type="state", name=name, fips_code=meta["state_fips"])
        if re.search(rf"\b{re.escape(abbreviation)}\b", text):
            return Geography(type="state", name=name, fips_code=meta["state_fips"])
    return None


def find_states(text: str) -> list[Geography]:
    states = load_states()
    found: list[Geography] = []
    for name, meta in states.items():
        aliases = [name, *meta.get("aliases", [])]
        abbreviation = meta["abbreviation"]
        if any(re.search(rf"\b{re.escape(alias)}\b", text, re.IGNORECASE) for alias in aliases) or re.search(
            rf"\b{re.escape(abbreviation)}\b", text
        ):
            found.append(Geography(type="state", name=name, fips_code=meta["state_fips"]))
    return found


def find_geographies(text: str) -> list[Geography]:
    found: list[Geography] = []
    for name, meta in load_named_geographies().items():
        aliases = [name, *meta.get("aliases", [])]
        if any(re.search(rf"\b{re.escape(alias)}\b", text, re.IGNORECASE) for alias in aliases):
            found.append(
                Geography(
                    type=meta.get("geography_type", "unknown"),
                    name=name,
                    county_fips=meta.get("county_fips", []),
                    parent=meta.get("parent"),
                    aliases=meta.get("aliases", []),
                )
            )
    parent_names = {geo.parent for geo in found if geo.parent}
    named_geo_names = {geo.name for geo in found if geo.name}
    for state in find_states(text):
        if state.name in parent_names:
            continue
        if any(state.name and state.name in name for name in named_geo_names):
            continue
        found.append(state)
    return found
