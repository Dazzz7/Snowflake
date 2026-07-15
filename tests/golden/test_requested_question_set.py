import pytest

from app.agent.orchestrator import CensusChatAgent
from app.agent.context_resolver import resolve_context
from app.agent.intent_parser import IntentParser
from app.agent.query_planner import QueryPlanner
from app.config import settings
from app.memory.conversation_state import ConversationState


REQUESTED_QUESTIONS = [
    ("Which state has the highest population?", "success", "ranking", "Total population"),
    ("Which state has the most people age 65 and older?", "success", "ranking", "Population age 65 and older"),
    ("Which state has the highest median household income?", "success", "ranking", "Median household income"),
    ("Which state has the highest poverty rate?", "success", "ranking", "Poverty rate"),
    ("Which state has the most uninsured residents?", "success", "ranking", "Uninsured residents"),
    ("Which state has the highest broadband-access rate?", "success", "ranking", "Broadband access rate"),
    ("Which state has the most households receiving SNAP?", "success", "ranking", "Households receiving SNAP"),
    ("Compare California and Texas by population.", "success", "comparison", "Total population"),
    ("Compare California and Texas by median income.", "success", "comparison", "Median household income"),
    ("Show the age distribution of California.", "success", "age_breakdown", "Population by age group"),
    ("Show the racial distribution of Georgia.", "success", "race_breakdown", "Population by race"),
    ("What percentage of Florida residents are over 65?", "success", "aggregate_metric", "Percentage of residents age 65 and older"),
    ("Which counties in New York have more than 500,000 residents?", "success", "filter", "Total population"),
    ("Which state has the highest bachelor's-degree attainment rate?", "success", "ranking", "Bachelor's-degree attainment rate"),
    ("What about NYC?", "success", "aggregate_metric", "Bachelor's-degree attainment rate"),
    ("What is second?", "success", "ranking", "Bachelor's-degree attainment rate"),
    ("Compare it with Texas.", "success", "comparison", "Bachelor's-degree attainment rate"),
    ("Show me the top five.", "success", "ranking", "Bachelor's-degree attainment rate"),
    ("What data can you answer questions about?", "metadata", "metadata", None),
]


def test_requested_question_set_plans_without_demo_data():
    object.__setattr__(settings, "use_llm", False)
    state = ConversationState("requested-question-planning")
    parser = IntentParser()
    planner = QueryPlanner()

    for question, status, question_type, metric in REQUESTED_QUESTIONS:
        if status == "metadata":
            continue
        resolved_question = resolve_context(question, state)
        intent = parser.parse(resolved_question)
        plan, validation = planner.create_plan(intent)
        assert validation.is_valid, f"{question}: {validation.reason}"
        assert plan is not None, question
        assert plan.query_type == question_type, question
        if metric:
            assert plan.metric.display_name == metric, question
        result_rows = [{"STATE_FIPS": "06", "VALUE": 1}]
        state.remember(
            intent.metric,
            intent.geographies,
            plan.metric.year,
            intent.intent,
            geography_level=plan.geography_level,
            geography_scope=plan.geography_scope,
            operation_type=plan.operation_type,
            sort_direction=plan.sort_direction,
            limit=plan.row_limit,
            result_rows=result_rows,
        )


@pytest.mark.skipif(not settings.has_snowflake_credentials, reason="Snowflake credentials are required for real-data golden answers.")
def test_requested_question_set_answers_from_snowflake():
    object.__setattr__(settings, "use_llm", False)
    agent = CensusChatAgent()
    for question, status, question_type, metric in REQUESTED_QUESTIONS:
        response = agent.answer(question, "requested-question-set-snowflake")
        diagnostic = f"{question}\nstatus={response.status}\nanswer={response.answer}\nsql={response.sql}"
        assert response.status == status, diagnostic
        assert response.interpretation.get("question_type") == question_type, diagnostic
        if metric:
            assert response.interpretation.get("metric") == metric, diagnostic
        assert response.answer, diagnostic
