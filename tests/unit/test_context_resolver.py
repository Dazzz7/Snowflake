from app.agent.context_resolver import resolve_context
from app.memory.conversation_state import ConversationState


def test_second_follow_up_uses_previous_ranking_context():
    state = ConversationState(
        session_id="test",
        last_metric="total_population",
        last_query_type="ranking",
        last_geography_level="state",
    )
    assert resolve_context("What is second?", state) == "Show rank 2 state by total_population"


def test_top_n_follow_up_uses_previous_ranking_context():
    state = ConversationState(
        session_id="test",
        last_metric="total_population",
        last_query_type="ranking",
        last_geography_level="state",
    )
    assert resolve_context("Show me top 5.", state) == "Show top 5 states by total_population"


def test_nyc_follow_up_inherits_previous_metric():
    state = ConversationState(
        session_id="test",
        last_metric="total_population",
        last_query_type="aggregate_metric",
        last_geography_level="state",
    )
    assert resolve_context("what about nyc?", state) == "What is the total_population of New York City?"
