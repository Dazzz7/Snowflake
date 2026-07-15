from app.agent.intent_parser import IntentParser
from app.config import settings


class FakeHostedLLM:
    def __init__(self) -> None:
        self.calls = 0

    def generate_json(self, system: str, user: str) -> dict:
        self.calls += 1
        return {
            "rewritten_question": "Which state has the highest population?",
        }


def test_public_mode_does_not_instantiate_llm_without_hosted_config():
    object.__setattr__(settings, "use_llm", False)
    object.__setattr__(settings, "llm_base_url", "")
    object.__setattr__(settings, "llm_model", "")
    parser = IntentParser()
    assert parser.llm is None
    intent = parser.parse("Which state has the highest population?")
    assert intent.intent == "ranking"
    assert intent.metric == "total_population"


def test_configured_hosted_llm_is_attempted_for_supported_questions():
    llm = FakeHostedLLM()
    parser = IntentParser(llm=llm)
    intent = parser.parse("Which state has the highest population?")
    assert llm.calls == 1
    assert intent.llm_attempted is True
    assert intent.llm_succeeded is True
    assert intent.intent == "ranking"
    assert intent.metric == "total_population"
