from __future__ import annotations

import json
import re
import time
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
        self.last_error: str | None = None

    def _chat(self, messages: list[dict[str, str]], temperature: float = 0.0, max_tokens: int = 900) -> str | None:
        self.last_error = None
        if not self.base_url or not self.model:
            self.last_error = "LLM base URL or model is not configured."
            return None
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "us-census-data-assistant/1.0",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=data,
            headers=headers,
            method="POST",
        )
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_seconds) as response:
                    body = json.loads(response.read().decode("utf-8"))
                    message = body.get("choices", [{}])[0].get("message", {})
                    content = message.get("content")
                    if isinstance(content, list):
                        return "".join(
                            item.get("text", "") if isinstance(item, dict) else str(item)
                            for item in content
                        )
                    return content
            except urllib.error.HTTPError as exc:
                self.last_error = f"LLM HTTP error {exc.code}."
                if exc.code == 429 and attempt < 2:
                    time.sleep(4 * (attempt + 1))
                    continue
                return None
            except urllib.error.URLError as exc:
                self.last_error = f"LLM connection error: {exc.reason}."
                return None
            except TimeoutError:
                self.last_error = "LLM request timed out."
                return None
            except (json.JSONDecodeError, IndexError, KeyError, TypeError) as exc:
                self.last_error = f"LLM response parse error: {type(exc).__name__}."
                return None
        return None

    def generate_json(self, system: str, user: str) -> dict[str, Any] | None:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        for attempt in range(2):
            content = self._chat(messages, max_tokens=900)
            parsed = self._parse_json_content(content)
            if parsed is not None:
                return parsed
            messages = [
                {"role": "system", "content": "Return one valid JSON object only. No markdown, no prose."},
                {"role": "user", "content": f"Convert this response into valid JSON only:\n{content or ''}"},
            ]
        return None

    def _parse_json_content(self, content: str | None) -> dict[str, Any] | None:
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
            max_tokens=700,
        )
