from __future__ import annotations

from app.agent.hosted_llm_client import HostedLLMClient
from app.agent.narrow_llm_agent import NarrowLLMCensusAgent
from app.models.response_models import AgentResponse


class CensusChatAgent:
    """Compatibility wrapper for the narrowed LLM-first Census agent."""

    def __init__(self, llm: HostedLLMClient | None = None) -> None:
        self.agent = NarrowLLMCensusAgent(llm=llm)

    def answer(self, question: str, session_id: str) -> AgentResponse:
        return self.agent.answer(question, session_id)
