from app.agent.orchestrator import CensusChatAgent


def test_verified_metric_takes_precedence_over_dynamic_discovery():
    agent = CensusChatAgent()

    assert agent._should_try_dynamic_semantic_first("Which state has the most uninsured residents?") is False


def test_specific_unknown_concept_can_override_generic_population_words():
    agent = CensusChatAgent()

    assert agent._should_try_dynamic_semantic_first("What percentage of Florida residents are veterans?") is True
