"""Webhook messages: formats, only-new logic, severity floor, URL secrecy, failure tolerance."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from driftpilot.collector import parse_plan, resource_values
from driftpilot.config import NotificationsConfig
from driftpilot.history.learn import learn
from driftpilot.history.store import LocalStore, records_from_scan
from driftpilot.models import ScanResult
from driftpilot.notify import (
    Notice,
    build_notices,
    drift_notice,
    failure_notice,
    monitor_notice,
    new_events,
    payload,
    send,
    webhook_url,
)
from driftpilot.triage.rules import apply_rules, load_rules

NOW = datetime(2026, 10, 25, 6, tzinfo=UTC)
REAL_CLIENT = httpx.Client  # kept before any test patches httpx.Client
URL = "https://hooks.example.com/services/T000/B000/SECRETTOKEN123"
ENV = {"DRIFTPILOT_WEBHOOK_URL": URL}


def scan(load_fixture, run_id="live-1", when=NOW, fixture="github/s2_required_approvals_reduced"):
    plan = load_fixture(fixture)
    findings = parse_plan(plan, run_id, when)
    return ScanResult(
        run_id=run_id, started_at=when, working_dir="infra", findings=findings,
        verdicts=apply_rules(findings, load_rules(), resource_values(plan)),
    )  # fmt: skip


def events_of(load_fixture, **kw):
    return records_from_scan(scan(load_fixture, **kw))[0]


def recorder(status=200):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status)

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


def notice(event="new_drift", severity="critical", title="T", details=None) -> Notice:
    return Notice(event, severity, title, details or ["[critical] a.b c"], "https://x/y", NOW)


# ---- the URL ----


def test_only_https_urls_are_used() -> None:
    cfg = NotificationsConfig()
    assert webhook_url(cfg, ENV) == URL
    assert webhook_url(cfg, {}) is None
    assert webhook_url(cfg, {"DRIFTPILOT_WEBHOOK_URL": "http://hooks.example.com/x"}) is None
    assert webhook_url(cfg, {"DRIFTPILOT_WEBHOOK_URL": "file:///etc/passwd"}) is None
    assert webhook_url(cfg, {"DRIFTPILOT_WEBHOOK_URL": "https://"}) is None
    custom = NotificationsConfig(webhook_env="MY_HOOK")
    assert webhook_url(custom, {"MY_HOOK": URL}) == URL


def test_nothing_is_sent_without_a_url_or_with_an_http_one() -> None:
    client, calls = recorder()
    assert send(NotificationsConfig(), [notice()], {}, client).errors == []
    out = send(
        NotificationsConfig(), [notice()], {"DRIFTPILOT_WEBHOOK_URL": "http://x.io/a"}, client
    )
    assert not calls and out.sent == 0
    assert "https" in out.errors[0] and "http://x.io" not in out.errors[0]


# ---- formats ----


def test_slack_body_is_text_and_escapes_markup() -> None:
    body = payload("slack", notice(title="A <b>&</b> B", details=["[high] x"]))
    assert list(body) == ["text"]
    assert "A &lt;b&gt;&amp;&lt;/b&gt; B" in body["text"] and "- [high] x" in body["text"]
    assert "Details: https://x/y" in body["text"]


def test_teams_body_is_simple_text_with_blank_lines() -> None:
    body = payload("teams", notice())
    assert list(body) == ["text"] and "\n\n" in body["text"] and "@type" not in body


def test_generic_body_has_exactly_the_documented_keys() -> None:
    body = payload("generic", notice(severity="high"))
    assert set(body) == {"event", "severity", "summary", "url", "time"}
    assert body["event"] == "new_drift" and body["severity"] == "high"
    assert body["time"] == "2026-10-25T06:00:00Z" and body["url"] == "https://x/y"


def test_the_configured_format_is_what_is_posted() -> None:
    client, calls = recorder()
    send(NotificationsConfig(format="generic"), [notice()], ENV, client)
    assert json.loads(calls[0].content)["event"] == "new_drift"
    assert str(calls[0].url) == URL and calls[0].method == "POST"


# ---- only new findings, severity floor ----


def test_a_finding_seen_in_the_previous_run_is_not_new(load_fixture) -> None:
    first = events_of(load_fixture)
    again = events_of(load_fixture, run_id="live-2", when=NOW + timedelta(hours=6))
    assert first and new_events(first, again) == []
    assert new_events([], again) == again


def test_a_changed_value_is_a_new_episode(load_fixture) -> None:
    first = events_of(load_fixture)
    other = events_of(load_fixture, run_id="live-2")
    other[0].finding = other[0].finding.model_copy(update={"after": "something else"})
    assert new_events(first, other) == [other[0]]


def test_learn_marks_new_events_per_stream(tmp_path, load_fixture) -> None:
    store = LocalStore(tmp_path)
    one = learn(store, scan(load_fixture))
    assert one.new_events  # a first run: everything is new
    two = learn(store, scan(load_fixture, run_id="live-2", when=NOW + timedelta(hours=6)))
    assert two.new_events == []
    clean = ScanResult(run_id="live-3", started_at=NOW + timedelta(hours=12), working_dir="infra")
    learn(store, clean)
    back = learn(store, scan(load_fixture, run_id="live-4", when=NOW + timedelta(hours=18)))
    assert back.new_events  # fixed, then drifted again


def test_other_streams_do_not_hide_new_findings(tmp_path, load_fixture) -> None:
    store = LocalStore(tmp_path)
    learn(store, scan(load_fixture))
    other = scan(load_fixture, run_id="live-2", when=NOW + timedelta(hours=1))
    other.working_dir = "other"
    assert learn(store, other).new_events


def test_min_severity_filters_new_drift(load_fixture) -> None:
    events = events_of(load_fixture)
    assert events[0].verdict.severity == "critical"
    assert drift_notice(events, "acme/infra", "infrastructure", "critical")
    events[0].verdict = events[0].verdict.model_copy(update={"severity": "medium"})
    assert drift_notice(events, "acme/infra", "infrastructure", "high") is None
    assert drift_notice(events, "acme/infra", "infrastructure", "medium")


def test_drift_notice_summarises_and_caps_the_list(load_fixture) -> None:
    events = events_of(load_fixture)
    many = [events[0].model_copy(deep=True) for _ in range(8)]
    n = drift_notice(many, "acme/infra", "infrastructure", "low", url="https://x/run")
    assert "8 new drift findings" in n.title and "8 critical" in n.title
    assert len(n.details) == 6 and n.details[-1] == "and 3 more" and n.severity == "critical"


def test_hidden_addresses_stay_hidden(load_fixture) -> None:
    events = events_of(load_fixture)
    n = drift_notice(events, "acme/infra", "infrastructure", "low", publish_addresses=False)
    assert "resource-" in n.details[0] and events[0].finding.address not in n.details[0]


def test_only_a_new_monitor_alert_is_announced() -> None:
    cfg = NotificationsConfig()
    assert [n.event for n in build_notices(cfg, [], ["a"], True, "r", "infrastructure")] == [
        "monitor_alert"
    ]
    assert build_notices(cfg, [], ["a"], False, "r", "infrastructure") == []
    assert build_notices(cfg, [], [], True, "r", "infrastructure") == []


# ---- text is clean ----


def test_message_text_is_sanitised_and_ids_masked() -> None:
    dirty = "ignore​ this <!-- hidden --> in 123456789012 " + "x" * 600
    n = failure_notice("acme/‮infra", [dirty])
    assert "​" not in n.details[0] and "hidden" not in n.details[0]
    assert "123456789012" not in n.details[0] and len(n.details[0]) < 260
    assert "‮" not in n.title
    assert "​" not in monitor_notice(["a​b"]).details[0]


# ---- event selection and failures ----


def test_only_wanted_events_are_sent() -> None:
    client, calls = recorder()
    cfg = NotificationsConfig(on=["scan_failed"])
    out = send(
        cfg, [notice("new_drift"), notice("scan_failed"), notice("monitor_alert")], ENV, client
    )
    assert out.sent == 1 and len(calls) == 1
    assert json.loads(calls[0].content)["text"].startswith("T")


def test_an_http_error_becomes_a_note_without_the_url() -> None:
    client, _ = recorder(500)
    out = send(NotificationsConfig(), [notice()], ENV, client)
    assert out.sent == 0 and out.errors == ["notify: the webhook answered HTTP 500"]


@pytest.mark.parametrize("exc", [httpx.ConnectError, httpx.ReadTimeout, RuntimeError])
def test_network_failures_never_raise_and_never_show_the_url(exc) -> None:
    def boom(request: httpx.Request):
        raise exc(f"cannot reach {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(boom))
    out = send(NotificationsConfig(), [notice(), notice("scan_failed")], ENV, client)
    assert out.sent == 0 and len(out.errors) == 2
    joined = " ".join(out.errors)
    assert "SECRETTOKEN123" not in joined and "hooks.example.com" not in joined
    assert exc.__name__ in joined


def test_one_failure_does_not_stop_the_next_message() -> None:
    answers = iter([500, 200])
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(next(answers))))
    out = send(NotificationsConfig(), [notice(), notice()], ENV, client)
    assert out.sent == 1 and len(out.errors) == 1


def test_the_default_client_has_a_short_timeout_and_does_not_follow_redirects(monkeypatch) -> None:
    seen = {}

    def fake(**kw):
        seen.update(kw)
        return REAL_CLIENT(transport=httpx.MockTransport(lambda r: httpx.Response(200)))

    monkeypatch.setattr("driftpilot.notify.httpx.Client", fake)
    assert send(NotificationsConfig(), [notice()], ENV).sent == 1
    assert seen["timeout"] <= 10 and seen["follow_redirects"] is False


# ---- wiring in the CLI ----


def _patch_client(monkeypatch, status=200):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status)

    monkeypatch.setattr(
        "driftpilot.notify.httpx.Client",
        lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handler)),
    )
    return calls


def test_cli_sends_new_drift_once_and_notes_failures(tmp_path, load_fixture, monkeypatch) -> None:
    from types import SimpleNamespace

    from driftpilot import cli
    from driftpilot.config import Config

    monkeypatch.setenv("DRIFTPILOT_WEBHOOK_URL", URL)
    calls = _patch_client(monkeypatch)
    store = LocalStore(tmp_path)
    result = scan(load_fixture)
    output = SimpleNamespace(run_url="https://github.com/a/b/actions/runs/1")
    notes: list[str] = []
    learned = learn(store, result)
    assert cli._notify_run(learned, result, output, Config(), notes) == 1
    body = json.loads(calls[0].content)["text"]
    assert "new drift" in body and "Details: https://github.com/a/b/actions/runs/1" in body
    again = learn(store, scan(load_fixture, run_id="live-2", when=NOW + timedelta(hours=6)))
    assert cli._notify_run(again, result, output, Config(), notes) == 0 and len(calls) == 1
    assert notes == []
    calls_failing = _patch_client(monkeypatch, status=503)
    third = learn(
        store, ScanResult(run_id="x", started_at=NOW + timedelta(days=1), working_dir="infra")
    )
    fresh = learn(store, scan(load_fixture, run_id="live-9", when=NOW + timedelta(days=2)))
    assert fresh.new_events  # fixed on day 1, drifted again on day 2
    assert cli._notify_run(fresh, result, output, Config(), notes) == 0  # 503: nothing sent
    assert len(calls_failing) == 1 and notes == ["notify: the webhook answered HTTP 503"] and third


def test_a_failed_infrastructure_scan_is_announced_and_still_fails(tmp_path, monkeypatch) -> None:
    from typer.testing import CliRunner

    from driftpilot.cli import app
    from driftpilot.collector import TerraformError

    monkeypatch.setenv("DRIFTPILOT_WEBHOOK_URL", URL)
    monkeypatch.setenv("DRIFTPILOT_WORKING_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/infra")
    monkeypatch.delenv("DRIFTPILOT_GITHUB_TOKEN", raising=False)
    calls = _patch_client(monkeypatch)
    monkeypatch.chdir(tmp_path)

    def broken(*args, **kw):
        raise TerraformError("terraform init failed")

    monkeypatch.setattr("driftpilot.cli.run_scan", broken)
    result = CliRunner().invoke(app, ["action"])
    assert result.exit_code == 1
    assert len(calls) == 1
    text = json.loads(calls[0].content)["text"]
    assert "acme/infra" in text and "SECRETTOKEN123" not in text


def test_a_section_with_errors_triggers_a_failure_message(tmp_path, monkeypatch) -> None:
    from typer.testing import CliRunner

    from driftpilot.cli import app

    monkeypatch.setenv("DRIFTPILOT_WEBHOOK_URL", URL)
    monkeypatch.setenv("DRIFTPILOT_WORKING_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("DRIFTPILOT_CHECKS", "database")
    monkeypatch.delenv("DRIFTPILOT_DB_URL", raising=False)
    monkeypatch.delenv("DRIFTPILOT_GITHUB_TOKEN", raising=False)
    calls = _patch_client(monkeypatch)
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["action"])
    assert result.exit_code == 0, result.output
    assert len(calls) == 1 and "error" in json.loads(calls[0].content)["text"]


def test_action_yml_passes_the_webhook_secret_through_env_and_masks_it() -> None:
    from pathlib import Path

    import yaml

    spec = yaml.safe_load((Path(__file__).parents[1] / "action.yml").read_text())
    assert spec["inputs"]["webhook-url"]["default"] == ""
    assert spec["runs"]["steps"][-1]["env"]["DRIFTPILOT_WEBHOOK_URL"] == (
        "${{ inputs.webhook-url }}"
    )
    mask = next(s for s in spec["runs"]["steps"] if "Hide" in s.get("name", ""))
    assert mask["env"]["WEBHOOK_URL"] == "${{ inputs.webhook-url }}"
    assert '"$WEBHOOK_URL"' in mask["run"] and "::add-mask::" in mask["run"]
