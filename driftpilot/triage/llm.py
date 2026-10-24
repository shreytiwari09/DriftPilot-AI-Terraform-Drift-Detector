"""The only way DriftPilot talks to an LLM (SPEC §4.4). Every prompt is redacted here first."""

import os
import re
import time
from collections.abc import Sequence
from typing import Any, Protocol

import httpx

from driftpilot.config import LLMConfig
from driftpilot.redact import scrub_patterns

# Pinned, not "-latest", so verdicts don't change silently. Flash-Lite: ~1.5 s per call and its own
# free quota; 3.5 Flash's free tier allows only 20 requests a day (measured Oct 2026).
DEFAULT_MODELS = {"gemini": "gemini-3.1-flash-lite", "ollama": "llama3.1:8b"}
_RETRY_DELAYS = (2, 5, 15)  # seconds; free tiers rate-limit per minute
_MAX_WAIT = 60  # a longer "retry in" means a daily quota: fail now instead of waiting
_RETRY_IN = re.compile(r"retry in ([0-9.]+)s|'retryDelay': '([0-9.]+)s'")


class LLMError(RuntimeError):
    pass


class LLMClient(Protocol):
    provider: str
    model: str

    def complete_json(self, system: str, prompt: str, schema: dict[str, Any]) -> str:
        """Return the model's raw text, asked to be JSON matching `schema`."""
        ...


class GeminiClient:
    provider = "gemini"

    def __init__(self, api_key: str, model: str, temperature: float) -> None:
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self.model = model
        self.temperature = temperature

    def complete_json(self, system: str, prompt: str, schema: dict[str, Any]) -> str:
        from google.genai import errors, types

        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=self.temperature,
            response_mime_type="application/json",
            response_json_schema=schema,
        )
        for attempt, delay in enumerate((*_RETRY_DELAYS, None)):
            try:
                response = self._client.models.generate_content(
                    model=self.model, contents=prompt, config=config
                )
                return response.text or ""
            except errors.APIError as e:
                retryable = e.code in (429, 500, 502, 503, 504)
                if match := _RETRY_IN.search(str(e)):
                    retryable = retryable and float(match.group(1) or match.group(2)) <= _MAX_WAIT
                if not retryable or delay is None:
                    raise LLMError(f"Gemini request failed (attempt {attempt + 1}): {e}") from e
                time.sleep(delay)
        raise AssertionError("unreachable")


class OllamaClient:
    """Local models over Ollama's HTTP API (`ollama serve`)."""

    provider = "ollama"

    def __init__(self, base_url: str, model: str, temperature: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature

    def complete_json(self, system: str, prompt: str, schema: dict[str, Any]) -> str:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "format": schema,
            "stream": False,
            "options": {"temperature": self.temperature},
        }
        try:
            response = httpx.post(f"{self.base_url}/api/chat", json=body, timeout=300)
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise LLMError(f"Ollama request failed: {e}") from e
        return response.json()["message"]["content"]


class FakeLLM:
    """Returns canned answers in order; records what it was asked. For tests."""

    provider = "fake"
    model = "fake"

    def __init__(self, responses: Sequence[str]) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    def complete_json(self, system: str, prompt: str, schema: dict[str, Any]) -> str:
        self.prompts.append(prompt)
        if not self.responses:
            raise LLMError("FakeLLM has no more responses")
        return self.responses.pop(0)


def ask(client: LLMClient, system: str, prompt: str, schema: dict[str, Any]) -> str:
    """Send a prompt after redacting it. All DriftPilot LLM calls go through here."""
    return client.complete_json(system, scrub_patterns(prompt), schema)


def build_llm(config: LLMConfig) -> LLMClient | None:
    """The configured client, or None if the LLM is disabled or has no key.

    Action inputs arrive as DRIFTPILOT_LLM_* env vars and override the config file.
    """
    if not config.enabled:
        return None
    provider = os.environ.get("DRIFTPILOT_LLM_PROVIDER") or config.provider
    model = os.environ.get("DRIFTPILOT_LLM_MODEL") or config.model or DEFAULT_MODELS[provider]
    if provider == "ollama":
        return OllamaClient(config.base_url, model, config.temperature)
    api_key = os.environ.get("DRIFTPILOT_LLM_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    return GeminiClient(api_key, model, config.temperature)
