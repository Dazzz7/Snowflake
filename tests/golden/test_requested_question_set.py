import pytest

from app.agent.orchestrator import CensusChatAgent
from app.config import settings


IN_SCOPE_QUESTIONS = [
    "What is the US population?",
    "What is the population of California?",
    "Which state has the highest population?",
    "Compare Texas and Florida population.",
    "How many people are over 65 in the US?",
    "Which state has the most people over 65?",
    "What is California's age distribution?",
    "Are there more males or females in Texas?",
    "Which state has the highest female population?",
    "What percentage of California is male?",
    "What is the racial distribution of Georgia?",
    "Which state has the largest Asian population?",
    "Compare the Black population of Texas and Florida.",
    "Which state has the largest land area?",
    "What is the land area of California?",
]

OUT_OF_SCOPE_QUESTIONS = [
    "What is the median income in California?",
    "How many veterans are in Texas?",
    "Tell me a joke.",
]


@pytest.mark.skipif(
    not (settings.has_snowflake_credentials and settings.has_hosted_llm_config),
    reason="Snowflake and hosted LLM credentials are required for narrowed live golden answers.",
)
def test_narrowed_question_set_answers_from_snowflake_and_llm():
    agent = CensusChatAgent()
    for question in IN_SCOPE_QUESTIONS:
        response = agent.answer(question, "narrowed-live-golden")
        diagnostic = f"{question}\nstatus={response.status}\nanswer={response.answer}\nsql={response.sql}"
        assert response.status == "success", diagnostic
        assert response.sql, diagnostic
        assert response.interpretation.get("llm_attempted") is True, diagnostic
        assert response.answer, diagnostic

    for question in OUT_OF_SCOPE_QUESTIONS:
        response = agent.answer(question, "narrowed-live-golden")
        diagnostic = f"{question}\nstatus={response.status}\nanswer={response.answer}"
        assert response.status == "out_of_scope", diagnostic
