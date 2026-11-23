from datetime import UTC, datetime
from pathlib import Path

from driftpilot.config import Config, OwnershipConfig, TeamRule
from driftpilot.models import (
    Context,
    DriftFinding,
    HistoryEvent,
    RunRecord,
    ScanResult,
    UnmanagedFinding,
)
from driftpilot.ownership import (
    Owner,
    apply_ownership,
    codeowners_team,
    mask_ids,
    team_from_tags,
)

NOW = datetime(2026, 11, 24, tzinfo=UTC)


def finding(address: str, fid: str = "f1", kind: str = "modified", before=None) -> DriftFinding:
    return DriftFinding(
        id=fid,
        run_id="r",
        detected_at=NOW,
        provider="p",
        resource_type=address.split(".")[0],
        address=address,
        change_kind=kind,
        attribute_path="x",
        before=before,
        after=1,
    )


def cfg(**ownership) -> Config:
    return Config(ownership=OwnershipConfig(**ownership))


def test_tag_wins_over_config_and_codeowners(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text('resource "aws_s3_bucket" "logs" {\n}\n')
    (tmp_path / "CODEOWNERS").write_text("*.tf @acme/infra\n")
    config = cfg(teams=[TeamRule(match="aws_s3_bucket.*", team="from-config")])
    owner = Owner(config, tmp_path)
    resources = {"aws_s3_bucket.logs": {"tags": {"team": "payments", "owner": "bob"}}}
    assert owner.team_for(finding("aws_s3_bucket.logs"), resources) == "payments"
    resources = {"aws_s3_bucket.logs": {"tags": {"owner": "bob"}}}
    assert owner.team_for(finding("aws_s3_bucket.logs"), resources) == "bob"  # tags.owner next


def test_config_glob_then_codeowners_then_default(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text('resource "docker_container" "web" {\n}\n')
    (tmp_path / "CODEOWNERS").write_text("# comment\n*.tf @acme/platform-team\n")
    config = cfg(
        teams=[TeamRule(match="github_repository.pay-*", team="payments")], default_team="misc"
    )
    owner = Owner(config, tmp_path)
    assert owner.team_for(finding("github_repository.pay-api"), {}) == "payments"
    assert owner.team_for(finding("docker_container.web"), {}) == "platform-team"
    assert owner.team_for(finding("docker_container.other"), {}) == "misc"  # no block in any .tf
    (tmp_path / "CODEOWNERS").unlink()
    assert Owner(config, tmp_path).team_for(finding("docker_container.web"), {}) == "misc"
    assert Owner(cfg(), tmp_path).team_for(finding("docker_container.web"), {}) == "unowned"


def test_codeowners_last_match_wins_and_paths(tmp_path: Path) -> None:
    root = tmp_path
    (root / ".github").mkdir()
    (root / ".github" / "CODEOWNERS").write_text(
        "* @acme/everyone\n/infra/ @acme/infra\n/infra/db/*.tf @alice\n*.md @docs\n"
    )
    assert codeowners_team(root, root / "infra" / "main.tf") == "infra"
    assert codeowners_team(root, root / "infra" / "db" / "x.tf") == "alice"
    assert codeowners_team(root, root / "other" / "main.tf") == "everyone"
    assert codeowners_team(root, root / "README.md") == "docs"
    assert codeowners_team(tmp_path / "nowhere", tmp_path / "nowhere" / "a.tf") is None


def test_codeowners_found_in_parent_of_working_dir(tmp_path: Path) -> None:
    infra = tmp_path / "infra"
    infra.mkdir()
    (infra / "main.tf").write_text('resource "github_repository" "a" {\n}\n')
    (tmp_path / "CODEOWNERS").write_text("/infra/ @acme/platform\n")
    owner = Owner(cfg(), infra)
    assert owner.team_for(finding("github_repository.a"), {}) == "platform"


def test_module_address_uses_the_module_call_file(tmp_path: Path) -> None:
    (tmp_path / "mods.tf").write_text('module "billing" {\n  source = "./m"\n}\n')
    (tmp_path / "CODEOWNERS").write_text("mods.tf @acme/billing\n")
    owner = Owner(cfg(), tmp_path)
    address = "module.billing.github_repository.x"
    assert owner.team_for(finding(address), {}) == "billing"


def test_tag_values_are_cleaned() -> None:
    assert team_from_tags({"tags": {"team": "pay​ments <!-- x -->"}}) == "payments"
    assert team_from_tags({"tags": {"team": "x" * 200}}) == "x" * 40 + "…"
    assert team_from_tags({"tags": {"team": ""}}) is None
    assert team_from_tags({"tags": None}) is None
    assert team_from_tags(None) is None
    assert team_from_tags({"tags": {"team": 5}}) is None


def test_deleted_resources_use_their_before_values(tmp_path: Path) -> None:
    gone = finding("aws_s3_bucket.logs", kind="deleted", before={"tags": {"team": "data"}})
    assert Owner(cfg(), tmp_path).team_for(gone, {}) == "data"


def test_mask_ids() -> None:
    assert mask_ids("acct 123456789012 ok") == "acct ************ ok"
    arn = "arn:aws:iam::123456789012:role/admin"
    assert mask_ids(f"by {arn}, again") == "by arn:***, again"
    assert mask_ids("1234567890123") == "1234567890123"  # 13 digits: not an account ID
    assert mask_ids(None) is None


def test_apply_ownership_fills_context_and_counts(tmp_path: Path) -> None:
    config = cfg(
        teams=[TeamRule(match="docker_container.*", team="platform")],
        environment="prod",
        account="123456789012",
        repo="acme/infra",
        default_team="misc",
    )
    unmanaged = UnmanagedFinding(
        id="u1",
        run_id="r",
        detected_at=NOW,
        provider="docker",
        resource_kind="container",
        resource_id="abc",
        name="handmade",
    )
    result = ScanResult(
        run_id="r",
        started_at=NOW,
        working_dir=str(tmp_path),
        findings=[finding("docker_container.web")],
        unmanaged=[unmanaged],
    )
    managed = [
        {"address": "docker_container.web", "values": {}},
        {"address": "docker_container.db", "values": {"tags": {"team": "data"}}},
        {"address": "github_repository.z", "values": {}},
    ]
    apply_ownership(result, config, tmp_path, {}, managed)
    assert result.context == Context(
        team="misc",
        repo="acme/infra",
        environment="prod",
        account="************",
        drift_type="infrastructure",
    )
    assert result.teams == {"f1": "platform", "u1": "misc"}
    assert result.managed_by_team == {"platform": 1, "data": 1, "misc": 1}


def test_apply_ownership_defaults_without_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    result = ScanResult(run_id="r", started_at=NOW, working_dir=str(tmp_path))
    apply_ownership(result, Config(), tmp_path, {}, None)
    assert result.context == Context()
    assert result.managed_by_team == {}
    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/infra")
    apply_ownership(result, Config(), tmp_path, {}, None)
    assert result.context.repo == "acme/infra"


def test_old_history_lines_still_load() -> None:
    event = (
        '{"run_id":"r","timestamp":"2026-10-25T00:00:00Z","finding":{"id":"i","run_id":"r",'
        '"detected_at":"2026-10-25T00:00:00Z","provider":"p","resource_type":"t","address":"t.a",'
        '"change_kind":"modified","attribute_path":"x","before":0,"after":1},'
        '"verdict":{"finding_id":"i","source":"rule","is_real_drift":true,"severity":"high",'
        '"category":"security","intent":"unknown","recommended_action":"revert",'
        '"confidence":1.0,"reason":"r"},"human_outcome":"pending"}'
    )
    assert HistoryEvent.model_validate_json(event).context == Context()
    run = (
        '{"run_id":"r","timestamp":"2026-10-25T00:00:00Z","working_dir":"infra","finding_count":0,'
        '"critical_count":0,"distinct_resources":0,"unmanaged_count":0,"noise_count":0}'
    )
    loaded = RunRecord.model_validate_json(run)
    assert (loaded.repo, loaded.environment, loaded.drift_type) == (
        "unknown",
        "unknown",
        "infrastructure",
    )
    assert loaded.managed_by_team == {}
