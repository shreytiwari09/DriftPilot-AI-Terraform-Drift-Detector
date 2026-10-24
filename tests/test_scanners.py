from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from driftpilot.scanners.base import find_unmanaged, parse_timestamp
from driftpilot.scanners.docker import DockerScanner
from driftpilot.scanners.github import GitHubScanner

NOW = datetime(2026, 10, 25, tzinfo=UTC)


def _docker_obj(id_, name, created="2026-10-24T17:40:12.123456789Z"):
    return SimpleNamespace(id=id_, name=name, attrs={"Created": created, "CreatedAt": created})


def test_docker_scanner_flags_hand_started_container(load_fixture) -> None:
    state = load_fixture("docker/s13_state_for_scanner")
    managed = DockerScanner(MagicMock(), "managed-by=terraform", []).managed_ids(state)
    client = MagicMock()
    client.containers.list.return_value = [
        _docker_obj(cid, "managed") for cid in managed if len(cid) == 64
    ] + [_docker_obj("2c9013fdef2a" + "0" * 52, "driftpilot-handmade")]
    client.networks.list.return_value = []
    client.volumes.list.return_value = [_docker_obj(None, "driftpilot-demo-cache-data")]

    scanner = DockerScanner(client, "managed-by=terraform", [])
    unmanaged = find_unmanaged(scanner, state, "r1", NOW)

    assert [(u.resource_kind, u.name) for u in unmanaged] == [("container", "driftpilot-handmade")]
    client.containers.list.assert_called_once_with(
        all=True, filters={"label": "managed-by=terraform"}
    )


def test_docker_ignore_names() -> None:
    client = MagicMock()
    client.containers.list.return_value = [_docker_obj("x" * 64, "ci-runner-1")]
    client.networks.list.return_value = []
    client.volumes.list.return_value = []
    scanner = DockerScanner(client, "managed-by=terraform", ["ci-runner-*"])
    assert find_unmanaged(scanner, {}, "r1", NOW) == []


def test_github_scanner_flags_new_repo_and_ignores_infra(load_fixture) -> None:
    state = load_fixture("github/state")
    org = MagicMock()
    org.get_repos.return_value = [
        SimpleNamespace(id=1432559917, name="demo-api", created_at=NOW),
        SimpleNamespace(id=1432559854, name="demo-web", created_at=NOW),
        SimpleNamespace(id=999, name="infra", created_at=NOW),
        SimpleNamespace(id=1000, name="demo-handmade", created_at=NOW),
    ]
    org.get_teams.return_value = [SimpleNamespace(id=20299439, slug="developers")]
    client = MagicMock()
    client.get_organization.return_value = org

    scanner = GitHubScanner(client, "driftpilot-demo", ["infra"])
    unmanaged = find_unmanaged(scanner, state, "r1", NOW)

    assert [(u.resource_kind, u.name, u.resource_id) for u in unmanaged] == [
        ("repository", "demo-handmade", "1000")
    ]
    client.get_organization.assert_called_once_with("driftpilot-demo")


def test_parse_timestamp() -> None:
    ts = parse_timestamp("2026-10-24T17:40:12.123456789Z")
    assert ts == datetime(2026, 10, 24, 17, 40, 12, 123456, tzinfo=UTC)
    assert parse_timestamp(None) is None
    assert parse_timestamp("garbage") is None
