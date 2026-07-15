from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

from app.config import settings


class HostedLLMClient:
    """Small OpenAI-compatible chat client for deployed, reachable LLM APIs."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.llm_api_key
        self.model = model or settings.llm_model
        self.timeout_seconds = timeout_seconds or settings.llm_timeout_seconds

    def _chat(self, messages: list[dict[str, str]], temperature: float = 0.0) -> str | None:
        if not self.base_url or not self.model:
            return None
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=data,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
                return body.get("choices", [{}])[0].get("message", {}).get("content")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, IndexError):
            return None

    def generate_json(self, system: str, user: str) -> dict[str, Any] | None:
        content = self._chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        )
        if not content:
            return None
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

    def generate_text(self, system: str, user: str) -> str | None:
        return self._chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
        )
