import json
from datetime import UTC, datetime
from pathlib import Path

from driftpilot.collector import parse_plan
from driftpilot.triage.llm import FakeLLM, LLMError
from driftpilot.triage.llm_triage import load_prompt, triage_findings, triage_resource

NOW = datetime(2026, 10, 25, tzinfo=UTC)
DEMO = Path(__file__).parents[1] / "demo"


def verdict(path, action="codify") -> dict:
    return {
        "attribute_path": path,
        "is_real_drift": True,
        "severity": "medium",
        "category": "availability",
        "intent": "likely_hotfix",
        "recommended_action": action,
        "confidence": 0.8,
        "reason": "Memory was raised by hand, probably to fix an outage.",
    }


def answer(*verdicts) -> str:
    return json.dumps({"verdicts": list(verdicts)})


def memory_findings(load_fixture):
    return parse_plan(load_fixture("docker/s11_memory_changed"), "r1", NOW)


def test_prompt_has_version() -> None:
    version, text = load_prompt("triage")
    assert version == "triage-v2"
    assert "prompt_version" not in text


def test_one_call_judges_all_changes_of_a_resource(load_fixture) -> None:
    findings = memory_findings(load_fixture)
    fake = FakeLLM([answer(verdict("memory"), verdict("memory_swap"))])
    out = triage_resource(fake, findings, DEMO / "docker")
    assert len(fake.prompts) == 1
    assert {v.recommended_action for v in out.values()} == {"codify"}
    assert {v.prompt_version for v in out.values()} == {"triage-v2"}
    sent = json.loads(fake.prompts[0].split("\n", 1)[1])
    assert sent["resource_code"].startswith('resource "docker_container" "web"')
    assert [c["attribute_path"] for c in sent["changes"]] == ["memory", "memory_swap"]


def test_missing_verdict_retries_once(load_fixture) -> None:
    findings = memory_findings(load_fixture)
    fake = FakeLLM([answer(verdict("memory")), answer(verdict("memory"), verdict("memory_swap"))])
    out = triage_resource(fake, findings)
    assert len(out) == 2 and "memory_swap" in fake.prompts[1]


def test_invalid_twice_falls_back_to_investigate(load_fixture) -> None:
    findings = memory_findings(load_fixture)
    out = triage_resource(FakeLLM(["not json", '{"verdicts": [{"severity": "huge"}]}']), findings)
    assert {(v.recommended_action, v.confidence) for v in out.values()} == {("investigate", 0.0)}


def test_partial_answer_keeps_good_verdicts(load_fixture) -> None:
    findings = memory_findings(load_fixture)
    out = triage_resource(FakeLLM([answer(verdict("memory"))] * 2), findings)
    by_path = {f.attribute_path: out[f.id] for f in findings}
    assert by_path["memory"].recommended_action == "codify"
    assert by_path["memory_swap"].recommended_action == "investigate"


def test_llm_error_falls_back(load_fixture) -> None:
    class Broken(FakeLLM):
        def complete_json(self, system, prompt, schema):
            raise LLMError("quota exceeded")

    out = triage_resource(Broken([]), memory_findings(load_fixture))
    assert all("quota exceeded" in v.reason for v in out.values())


def test_deleted_resource_uses_null_path(load_fixture) -> None:
    findings = parse_plan(load_fixture("docker/s10_container_removed"), "r", NOW)
    out = triage_resource(FakeLLM([answer(verdict(None, "recreate"))]), findings)
    assert next(iter(out.values())).recommended_action == "recreate"


def test_triage_findings_groups_by_resource_and_skips_decided(load_fixture) -> None:
    findings = memory_findings(load_fixture)
    decided = {findings[0].id: object()}
    fake = FakeLLM([answer(verdict("memory_swap"))])
    out = triage_findings(fake, findings, decided)
    assert list(out) == [findings[1].id] and len(fake.prompts) == 1
