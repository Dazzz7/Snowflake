from __future__ import annotations

try:
    from fastapi import FastAPI
    from pydantic import BaseModel
except ImportError:  # pragma: no cover - lets core modules import without API deps.
    FastAPI = None
    BaseModel = object

from app.agent.orchestrator import CensusChatAgent


agent = CensusChatAgent()

if FastAPI:
    app = FastAPI(title="US Census Data Assistant")

    class ChatRequest(BaseModel):
        question: str
        session_id: str = "default"

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/chat")
    def chat(request: ChatRequest) -> dict:
        response = agent.answer(request.question, request.session_id)
        return {
            "answer": response.answer,
            "status": response.status,
            "interpretation": response.interpretation,
            "sql": response.sql,
            "rows": response.rows,
        }

