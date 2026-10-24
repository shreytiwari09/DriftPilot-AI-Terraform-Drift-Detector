import json
from datetime import UTC, datetime
from pathlib import Path

from driftpilot.collector import parse_plan
from driftpilot.triage.llm import FakeLLM, LLMError
from driftpilot.triage.llm_triage import load_prompt, triage_findings, triage_one

NOW = datetime(2026, 10, 25, tzinfo=UTC)
DEMO = Path(__file__).parents[1] / "demo"

GOOD = json.dumps(
    {
        "is_real_drift": True,
        "severity": "medium",
        "category": "availability",
        "intent": "likely_hotfix",
        "recommended_action": "codify",
        "confidence": 0.8,
        "reason": "Memory was raised by hand, probably to fix an outage.",
    }
)


def memory_findings(load_fixture):
    return parse_plan(load_fixture("docker/s11_memory_changed"), "r1", NOW)


def test_prompt_has_version() -> None:
    version, text = load_prompt("triage")
    assert version == "triage-v1"
    assert "prompt_version" not in text


def test_valid_answer_becomes_llm_verdict(load_fixture) -> None:
    findings = memory_findings(load_fixture)
    fake = FakeLLM([GOOD])
    v = triage_one(fake, findings[0], findings[1:], DEMO / "docker")
    assert (v.source, v.recommended_action, v.intent, v.prompt_version) == (
        "llm",
        "codify",
        "likely_hotfix",
        "triage-v1",
    )
    sent = json.loads(fake.prompts[0].split("\n", 1)[1])
    assert sent["attribute_path"] == "memory"
    assert sent["resource_code"].startswith('resource "docker_container" "web"')
    assert sent["other_changes_on_resource"][0]["attribute_path"] == "memory_swap"


def test_invalid_then_valid_retries_once(load_fixture) -> None:
    findings = memory_findings(load_fixture)
    fake = FakeLLM(['{"severity": "huge"}', GOOD])
    v = triage_one(fake, findings[0], [])
    assert v.recommended_action == "codify"
    assert "not valid for the schema" in fake.prompts[1]


def test_invalid_twice_falls_back_to_investigate(load_fixture) -> None:
    findings = memory_findings(load_fixture)
    v = triage_one(FakeLLM(["not json", "{}"]), findings[0], [])
    assert (v.recommended_action, v.confidence) == ("investigate", 0.0)
    assert "invalid twice" in v.reason


def test_llm_error_falls_back(load_fixture) -> None:
    class Broken(FakeLLM):
        def complete_json(self, system, prompt, schema):
            raise LLMError("quota exceeded")

    findings = memory_findings(load_fixture)
    v = triage_one(Broken([]), findings[0], [])
    assert v.recommended_action == "investigate"
    assert "quota exceeded" in v.reason


def test_triage_findings_skips_decided(load_fixture) -> None:
    findings = memory_findings(load_fixture)
    decided = {findings[0].id: object()}
    out = triage_findings(FakeLLM([GOOD]), findings, decided)
    assert list(out) == [findings[1].id]
