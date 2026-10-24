import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from driftpilot.models import UnmanagedFinding
from driftpilot.remediate.importer import import_block, import_resource
from driftpilot.remediate.verify import VerifyResult
from driftpilot.scanners import import_target
from driftpilot.scanners.base import ImportTarget, tf_name
from driftpilot.scanners.docker import PROVIDER as DOCKER
from driftpilot.scanners.github import PROVIDER as GITHUB
from driftpilot.triage.llm import FakeLLM

NOW = datetime(2026, 10, 25, tzinfo=UTC)
GENERATED = (
    'resource "github_repository" "demo_handmade" {\n  name = "demo-handmade"\n  etag = null\n}'
)
TARGET = ImportTarget("github_repository", "demo-handmade", "demo_handmade")


def unmanaged(provider, kind, rid, name) -> UnmanagedFinding:
    return UnmanagedFinding(
        id="u",
        run_id="r",
        detected_at=NOW,
        provider=provider,
        resource_kind=kind,
        resource_id=rid,
        name=name,
    )


def test_import_targets_per_provider() -> None:
    repo = import_target(unmanaged(GITHUB, "repository", "1000", "demo-handmade"))
    assert (repo.address, repo.import_id) == ("github_repository.demo_handmade", "demo-handmade")
    team = import_target(unmanaged(GITHUB, "team", "42", "on-call"))
    assert (team.tf_type, team.import_id) == ("github_team", "42")
    box = import_target(unmanaged(DOCKER, "container", "abc123", "driftpilot-handmade"))
    assert (box.address, box.import_id) == ("docker_container.driftpilot_handmade", "abc123")
    assert import_target(unmanaged("other", "x", "1", "y")) is None


def test_tf_name() -> None:
    assert tf_name("Demo-Handmade.v2") == "demo_handmade_v2"
    assert tf_name("123abc") == "r_123abc"


def test_import_block() -> None:
    assert import_block(TARGET) == (
        'import {\n  to = github_repository.demo_handmade\n  id = "demo-handmade"\n}\n'
    )


def fake_generate(args, cwd, timeout):
    assert "-generate-config-out=generated.tf" in args
    assert "to = github_repository.demo_handmade" in (cwd / "driftpilot_import.tf").read_text()
    (cwd / "generated.tf").write_text("# __generated__ by Terraform\n" + GENERATED + "\n")
    return subprocess.CompletedProcess(args, 2, "Plan: 1 to import", "")


def workdir(tmp_path: Path) -> Path:
    d = tmp_path / "infra"
    d.mkdir()
    (d / "main.tf").write_text('resource "github_repository" "api" {\n  name = "demo-api"\n}\n')
    return d


def test_llm_tidied_import_is_verified(tmp_path: Path) -> None:
    tidy = 'resource "github_repository" "demo_handmade" {\n  name = "demo-handmade"\n}'
    fake = FakeLLM([json.dumps({"block": tidy})])
    ok = VerifyResult(True, "plan", "Plan: 1 to import, 0 to add, 0 to change, 0 to destroy.")
    with (
        patch("driftpilot.remediate.importer.run_terraform", side_effect=fake_generate),
        patch("driftpilot.remediate.importer.verify_patch", return_value=ok) as verify,
    ):
        result = import_resource(fake, workdir(tmp_path), TARGET)
    assert result.verified and result.note == "import-v1"
    files = verify.call_args.args[1]
    assert list(files) == ["imported_demo_handmade.tf"]
    assert files["imported_demo_handmade.tf"].startswith("import {")
    assert verify.call_args.kwargs == {"expect": "import_only", "targets": [TARGET.address]}
    sent = json.loads(fake.prompts[0].split("\n", 1)[1])
    assert sent["generated_block"].startswith('resource "github_repository"')
    assert sent["style_example"].startswith('resource "github_repository" "api"')


def test_falls_back_to_generated_config(tmp_path: Path) -> None:
    results = [VerifyResult(False, "validate", "bad"), VerifyResult(True, "plan", "1 to import")]
    fake = FakeLLM([json.dumps({"block": "resource x"})])
    with (
        patch("driftpilot.remediate.importer.run_terraform", side_effect=fake_generate),
        patch("driftpilot.remediate.importer.verify_patch", side_effect=results) as verify,
    ):
        result = import_resource(fake, workdir(tmp_path), TARGET, max_retries=1)
    assert result.verified and result.note == "generated config"
    assert "etag = null" in verify.call_args.args[1]["imported_demo_handmade.tf"]


def test_generate_failure(tmp_path: Path) -> None:
    def fail(args, cwd, timeout):
        return subprocess.CompletedProcess(args, 1, "", "Error: Cannot import non-existent object")

    with patch("driftpilot.remediate.importer.run_terraform", side_effect=fail):
        result = import_resource(None, workdir(tmp_path), TARGET)
    assert not result.verified and "non-existent" in result.proof
