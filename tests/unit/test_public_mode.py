from app.agent.intent_parser import IntentParser
from app.config import settings


def test_public_mode_does_not_instantiate_llm_without_hosted_config():
    object.__setattr__(settings, "use_llm", False)
    object.__setattr__(settings, "llm_base_url", "")
    object.__setattr__(settings, "llm_model", "")
    parser = IntentParser()
    assert parser.llm is None
    intent = parser.parse("Which state has the highest population?")
    assert intent.intent == "ranking"
    assert intent.metric == "total_population"
