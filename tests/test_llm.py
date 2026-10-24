from unittest.mock import MagicMock, patch

import httpx
import pytest

from driftpilot.config import LLMConfig
from driftpilot.triage.llm import (
    DEFAULT_MODELS,
    FakeLLM,
    GeminiClient,
    LLMError,
    OllamaClient,
    ask,
    build_llm,
)

SCHEMA = {"type": "object"}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch) -> None:
    for name in (
        "GEMINI_API_KEY",
        "DRIFTPILOT_LLM_API_KEY",
        "DRIFTPILOT_LLM_PROVIDER",
        "DRIFTPILOT_LLM_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_ask_redacts_before_sending() -> None:
    fake = FakeLLM(['{"ok": true}'])
    token = "ghp_" + "x" * 36
    assert ask(fake, "sys", f"value was {token}", SCHEMA) == '{"ok": true}'
    assert token not in fake.prompts[0]
    assert "<redacted>" in fake.prompts[0]


def test_fake_llm_runs_out() -> None:
    with pytest.raises(LLMError):
        FakeLLM([]).complete_json("s", "p", SCHEMA)


def test_build_llm_none_without_key_or_when_disabled(monkeypatch) -> None:
    assert build_llm(LLMConfig()) is None
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert build_llm(LLMConfig(enabled=False)) is None


def test_build_llm_gemini_default_model_and_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    with patch("google.genai.Client") as client_cls:
        client = build_llm(LLMConfig())
        assert isinstance(client, GeminiClient)
        assert client.model == DEFAULT_MODELS["gemini"]
        client_cls.assert_called_once_with(api_key="k")

        monkeypatch.setenv("DRIFTPILOT_LLM_API_KEY", "action-key")
        monkeypatch.setenv("DRIFTPILOT_LLM_MODEL", "other-model")
        client = build_llm(LLMConfig(model="config-model"))
        assert client.model == "other-model"
        client_cls.assert_called_with(api_key="action-key")


def test_build_llm_ollama_needs_no_key(monkeypatch) -> None:
    monkeypatch.setenv("DRIFTPILOT_LLM_PROVIDER", "ollama")
    client = build_llm(LLMConfig())
    assert isinstance(client, OllamaClient)
    assert client.model == DEFAULT_MODELS["ollama"]


def test_gemini_retries_rate_limit_then_succeeds() -> None:
    from google.genai import errors

    with patch("google.genai.Client") as client_cls, patch("driftpilot.triage.llm.time.sleep"):
        generate = client_cls.return_value.models.generate_content
        generate.side_effect = [
            errors.APIError(429, {"error": {"message": "slow down"}}),
            MagicMock(text='{"ok": 1}'),
        ]
        client = GeminiClient("k", "m", 0.1)
        assert client.complete_json("sys", "prompt", SCHEMA) == '{"ok": 1}'
    config = generate.call_args.kwargs["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema == SCHEMA
    assert config.system_instruction == "sys"


def test_gemini_daily_quota_fails_fast() -> None:
    from google.genai import errors

    with (
        patch("google.genai.Client") as client_cls,
        patch("driftpilot.triage.llm.time.sleep") as sleep,
    ):
        client_cls.return_value.models.generate_content.side_effect = errors.APIError(
            429, {"error": {"message": "Quota exceeded. Please retry in 29027.5s."}}
        )
        with pytest.raises(LLMError, match="Quota exceeded"):
            GeminiClient("k", "m", 0.1).complete_json("s", "p", SCHEMA)
    sleep.assert_not_called()


def test_gemini_non_retryable_error_raises() -> None:
    from google.genai import errors

    with patch("google.genai.Client") as client_cls:
        client_cls.return_value.models.generate_content.side_effect = errors.APIError(
            404, {"error": {"message": "no such model"}}
        )
        with pytest.raises(LLMError, match="no such model"):
            GeminiClient("k", "m", 0.1).complete_json("s", "p", SCHEMA)


def test_ollama_request_shape() -> None:
    response = httpx.Response(
        200,
        json={"message": {"content": '{"ok": 2}'}},
        request=httpx.Request("POST", "http://x/api/chat"),
    )
    with patch("driftpilot.triage.llm.httpx.post", return_value=response) as post:
        out = OllamaClient("http://x/", "llama", 0.2).complete_json("sys", "prompt", SCHEMA)
    assert out == '{"ok": 2}'
    body = post.call_args.kwargs["json"]
    assert post.call_args.args[0] == "http://x/api/chat"
    assert body["format"] == SCHEMA
    assert body["stream"] is False
    assert body["messages"][0] == {"role": "system", "content": "sys"}
