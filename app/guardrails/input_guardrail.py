from __future__ import annotations

from dataclasses import dataclass


OFF_TOPIC_TERMS = {
    "malware",
    "phishing",
    "exploit",
    "sql injection",
    "password",
    "credit card",
    "stock price",
    "weather",
}

CENSUS_TERMS = {
    "population",
    "people",
    "residents",
    "income",
    "poverty",
    "uninsured",
    "insurance",
    "broadband",
    "internet",
    "snap",
    "food stamps",
    "bachelor",
    "degree",
    "education",
    "race",
    "racial",
    "percentage",
    "percent",
    "household",
    "housing",
    "age",
    "data",
    "topics",
    "available",
    "census",
    "county",
    "state",
    "states",
    "tract",
    "block group",
    "compare",
    "top",
    "rank",
    "highest",
    "higher",
    "lowest",
    "second",
    "largest",
}


@dataclass(frozen=True)
class ScopeDecision:
    in_scope: bool
    reason: str


def classify_input(question: str) -> ScopeDecision:
    lowered = question.lower()
    if any(term in lowered for term in OFF_TOPIC_TERMS):
        return ScopeDecision(False, "The request is outside the Census analytics scope.")
    if any(term in lowered for term in CENSUS_TERMS):
        return ScopeDecision(True, "The request appears to be about Census data.")
    return ScopeDecision(False, "The request does not mention a supported Census topic.")
