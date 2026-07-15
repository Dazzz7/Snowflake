from app.agent.orchestrator import CensusChatAgent
from app.agent.intent_parser import IntentParser


def test_verified_metric_takes_precedence_over_dynamic_discovery():
    agent = CensusChatAgent()

    assert agent._should_try_dynamic_semantic_first("Which state has the most uninsured residents?") is False


def test_specific_unknown_concept_can_override_generic_population_words():
    agent = CensusChatAgent()

    assert agent._should_try_dynamic_semantic_first("What percentage of Florida residents are veterans?") is True


def test_rental_units_does_not_match_shopping_distance():
    intent = IntentParser(llm=None).parse("Which Census Block Groups have over 100 rental units?")

    assert intent.metric != "shopping_distance"
    assert intent.geography_level == "block_group"


def test_average_age_routes_to_dynamic_planner_first():
    agent = CensusChatAgent()

    assert agent._should_try_dynamic_semantic_first("which state has the highest average age of residents") is True
