import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from driftpilot.collector import parse_plan
from driftpilot.remediate.codify import codify, ignore_changes
from driftpilot.remediate.verify import VerifyResult
from driftpilot.triage.llm import FakeLLM

NOW = datetime(2026, 10, 25, tzinfo=UTC)
DEMO = Path(__file__).parents[1] / "demo"


def docker_dir(tmp_path: Path) -> Path:
    d = tmp_path / "docker"
    shutil.copytree(DEMO / "docker", d, ignore=shutil.ignore_patterns(".terraform", "*.tfstate*"))
    return d


def memory_findings(load_fixture):
    return parse_plan(load_fixture("docker/s11_memory_changed"), "r", NOW)


def answer(block: str) -> str:
    return json.dumps({"block": block})


def test_codify_sends_block_and_settings_then_verifies(tmp_path, load_fixture) -> None:
    d = docker_dir(tmp_path)
    findings = memory_findings(load_fixture)
    fake = FakeLLM([answer('resource "docker_container" "web" {\n  memory = 512\n}')])
    with patch(
        "driftpilot.remediate.codify.verify_patch",
        return_value=VerifyResult(True, "plan", "No changes.", {"main.tf": "formatted"}),
    ) as verify:
        result = codify(fake, d, findings)
    assert (result.verified, result.attempts, result.proof) == (True, 1, "No changes.")
    assert result.files == {"main.tf": "formatted"}
    sent = json.loads(fake.prompts[0].split("\n", 1)[1])
    assert sent["resource_block"].startswith('resource "docker_container" "web"')
    assert {s["path"] for s in sent["settings"]} == {"memory", "memory_swap"}
    patched = verify.call_args.args[1]["main.tf"]
    assert "memory = 512" in patched and 'resource "docker_container" "cache"' in patched


def test_codify_feeds_terraform_error_back_and_retries(tmp_path, load_fixture) -> None:
    d = docker_dir(tmp_path)
    fake = FakeLLM(
        [
            answer('resource "docker_container" "web" { bad }'),
            answer('resource "docker_container" "web" {\n  memory = 512\n}'),
        ]
    )
    results = [
        VerifyResult(False, "validate", "Error: Unsupported block type"),
        VerifyResult(True, "plan", "No changes."),
    ]
    with patch("driftpilot.remediate.codify.verify_patch", side_effect=results):
        result = codify(fake, d, memory_findings(load_fixture))
    assert (result.verified, result.attempts) == (True, 2)
    assert "Unsupported block type" in fake.prompts[1]


def test_codify_gives_up_after_max_retries(tmp_path, load_fixture) -> None:
    d = docker_dir(tmp_path)
    fake = FakeLLM(["not json"] * 3)
    result = codify(fake, d, memory_findings(load_fixture), max_retries=3)
    assert (result.verified, result.attempts) == (False, 3)


def test_codify_refuses_sensitive_and_deleted(tmp_path, load_fixture) -> None:
    d = docker_dir(tmp_path)
    findings = memory_findings(load_fixture)
    secret = [findings[0].model_copy(update={"sensitive": True})]
    assert "sensitive" in codify(FakeLLM([]), d, secret).note
    deleted = parse_plan(load_fixture("docker/s10_container_removed"), "r", NOW)
    assert "recreate" in codify(FakeLLM([]), d, deleted).note


def test_ignore_changes_patch(tmp_path, load_fixture) -> None:
    d = docker_dir(tmp_path)
    findings = parse_plan(load_fixture("docker/s12_restart_policy_changed"), "r", NOW)
    with patch(
        "driftpilot.remediate.codify.verify_patch",
        return_value=VerifyResult(True, "plan", "No changes."),
    ) as verify:
        result = ignore_changes(d, findings)
    assert result.verified
    patched = verify.call_args.args[1]["main.tf"]
    assert "ignore_changes = [max_retry_count, restart]" in patched
