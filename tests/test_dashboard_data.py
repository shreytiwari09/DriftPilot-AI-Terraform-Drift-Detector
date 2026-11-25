import json

import pandas as pd

from driftpilot.report.dashboard.data import (
    compute_kpis,
    episode_records,
    episodes_csv,
    filter_episodes,
    hide_address,
    iso,
)

AS_OF = "2026-10-10T12:00:00Z"


def ep(address="t.a", start="2026-10-01T06:00:00Z", **kw) -> dict:
    base = {
        "id": address, "address": address, "attribute": "x", "resourceType": "t",
        "start": start, "end": start, "resolvedAt": None, "runsSeen": 1, "severity": "medium",
        "category": "availability", "action": "codify", "decidedBy": "llm", "outcome": "pending",
        "resolved": False, "team": "platform", "repo": "acme/infra", "environment": "prod",
        "account": "unknown", "driftType": "infrastructure",
    }  # fmt: skip
    return base | kw


def run(t="2026-10-10T06:00:00Z", managed=20, unmanaged=5, **kw) -> dict:
    base = {
        "t": t, "repo": "acme/infra", "environment": "prod", "driftType": "infrastructure",
        "dir": "infra", "managed": managed, "unmanaged": unmanaged, "managedByTeam": {},
        "unmanagedByTeam": {},
    }  # fmt: skip
    return base | kw


EPISODES = [
    ep("t.a", "2026-10-01T06:00:00Z", resolved=True, resolvedAt="2026-10-01T18:00:00Z",
       outcome="accepted", team="platform"),
    ep("t.b", "2026-10-02T06:00:00Z", resolved=True, resolvedAt="2026-10-03T06:00:00Z",
       outcome="overruled", team="payments", severity="critical", decidedBy="rule"),
    ep("t.c", "2026-10-05T06:00:00Z", severity="high", team="payments", environment="staging",
       outcome="accepted"),
    ep("t.d", "2026-10-06T06:00:00Z", team="platform", driftType="database", repo="acme/db"),
    ep("t.a", "2026-10-07T06:00:00Z", team="platform"),
    ep("t.a", "2026-10-08T06:00:00Z", team="platform"),
]  # fmt: skip


def test_filters_combine() -> None:
    assert len(filter_episodes(EPISODES, {})) == 6
    assert len(filter_episodes(EPISODES, {"team": "payments"})) == 2
    assert len(filter_episodes(EPISODES, {"team": "payments", "severity": "critical"})) == 1
    assert len(filter_episodes(EPISODES, {"driftType": "database"})) == 1
    assert len(filter_episodes(EPISODES, {"repo": "acme/db"})) == 1
    assert len(filter_episodes(EPISODES, {"environment": "staging"})) == 1
    assert len(filter_episodes(EPISODES, {"status": "open"})) == 4
    assert len(filter_episodes(EPISODES, {"status": "resolved"})) == 2
    assert len(filter_episodes(EPISODES, {"decidedBy": "rule"})) == 1
    assert len(filter_episodes(EPISODES, {"outcome": "accepted"})) == 2


def test_date_range_is_inclusive_by_start_day() -> None:
    both = {"from": "2026-10-02", "to": "2026-10-05"}
    assert [e["address"] for e in filter_episodes(EPISODES, both)] == ["t.b", "t.c"]
    assert len(filter_episodes(EPISODES, {"from": "2026-10-07"})) == 2
    assert len(filter_episodes(EPISODES, {"to": "2026-10-01"})) == 1


def test_search_looks_at_address_setting_team_repo() -> None:
    assert len(filter_episodes(EPISODES, {"search": "PAYMENTS"})) == 2
    assert len(filter_episodes(EPISODES, {"search": "t.d"})) == 1
    assert len(filter_episodes(EPISODES, {"search": "acme/db"})) == 1
    assert filter_episodes(EPISODES, {"search": "nothing"}) == []


def test_kpis_unfiltered() -> None:
    k = compute_kpis(EPISODES, [run()], {}, AS_OF)
    assert k["episodes"] == 6 and k["driftedResources"] == 4
    assert k["iacCoverage"] == 80.0  # 20 / (20 + 5)
    assert k["driftRate"] == 20.0  # 4 drifted / 20 managed
    assert k["openCount"] == 4
    assert k["oldestOpenHours"] == 126.0  # t.c, open since 10-05 06:00, 5.25 days before AS_OF
    assert k["mttrHours"] == 18.0  # (12 h + 24 h) / 2
    assert (k["decided"], k["overruleRate"], k["alertPrecision"]) == (3, 33.3, 66.7)
    assert k["recurringOffenders"] == 1  # t.a/x three times


def test_kpis_follow_the_filters() -> None:
    k = compute_kpis(EPISODES, [run()], {"team": "payments", "severity": "critical"}, AS_OF)
    assert k["episodes"] == 1 and k["openCount"] == 0 and k["oldestOpenHours"] is None
    assert k["overruleRate"] == 100.0 and k["alertPrecision"] == 0.0
    assert k["recurringOffenders"] == 0


def test_kpis_with_nothing_to_divide() -> None:
    k = compute_kpis([], [], {}, None)
    assert k["iacCoverage"] is None and k["driftRate"] is None and k["mttrHours"] is None
    assert k["overruleRate"] is None and k["openCount"] == 0
    assert compute_kpis(EPISODES, [run(managed=None)], {}, AS_OF)["iacCoverage"] is None
    assert compute_kpis(EPISODES, [run(managed=0, unmanaged=0)], {}, AS_OF)["driftRate"] is None


def test_denominators_use_the_latest_run_of_each_stream_in_the_range() -> None:
    runs = [
        run("2026-10-01T06:00:00Z", managed=10, unmanaged=0),
        run("2026-10-10T06:00:00Z", managed=20, unmanaged=5),
        run("2026-10-10T06:00:00Z", managed=30, unmanaged=0, repo="acme/db", driftType="database"),
    ]
    assert compute_kpis([], runs, {}, AS_OF)["managed"] == 50  # two streams, latest each
    assert compute_kpis([], runs, {"repo": "acme/db"}, AS_OF)["managed"] == 30
    assert compute_kpis([], runs, {"driftType": "infrastructure"}, AS_OF)["managed"] == 20
    assert compute_kpis([], runs, {"to": "2026-10-05"}, AS_OF)["managed"] == 10
    assert compute_kpis([], runs, {"from": "2026-11-01"}, AS_OF)["managed"] is None


def test_team_filter_uses_per_team_counts_or_says_unknown() -> None:
    split = run(managedByTeam={"platform": 12, "payments": 8}, unmanagedByTeam={"platform": 3})
    k = compute_kpis(EPISODES, [split], {"team": "platform"}, AS_OF)
    assert (k["managed"], k["unmanaged"], k["iacCoverage"]) == (12, 3, 80.0)
    assert k["driftRate"] == 16.7  # platform drifted on t.a and t.d: 2 of 12
    k = compute_kpis(EPISODES, [split], {"team": "payments"}, AS_OF)
    assert (k["managed"], k["unmanaged"]) == (8, 0)
    old = run()  # no per-team counts recorded: honest "unknown", never a wrong number
    k = compute_kpis(EPISODES, [old], {"team": "platform"}, AS_OF)
    assert k["iacCoverage"] is None and k["driftRate"] is None


def test_episode_records_mask_and_hide() -> None:
    frame = pd.DataFrame(
        [
            {
                "finding_id": "f", "address": "aws_iam_role.x",
                "attribute": "arn:aws:iam::123456789012:role/r",
                "resource_type": "aws_iam_role", "start": pd.Timestamp("2026-10-01T06:00:00Z"),
                "end": pd.Timestamp("2026-10-01T06:00:00Z"), "resolved_at": pd.NaT, "runs_seen": 1,
                "severity": "high", "category": "security", "action": "revert", "source": "rule",
                "outcome": "pending", "resolved": False, "team": "t", "repo": "r",
                "environment": "e", "account": "123456789012", "drift_type": "infrastructure",
            }
        ]
    )  # fmt: skip
    [rec] = episode_records(frame)
    assert rec["attribute"] == "arn:***" and rec["account"] == "************"
    assert rec["address"] == "aws_iam_role.x" and rec["resolvedAt"] is None
    assert rec["start"] == "2026-10-01T06:00:00Z" and rec["decidedBy"] == "rule"
    [hidden] = episode_records(frame, publish_addresses=False)
    assert hidden["address"] == hide_address("aws_iam_role.x") != "aws_iam_role.x"
    assert hide_address("a") == hide_address("a") != hide_address("b")
    json.dumps(rec)  # plain JSON values only


def test_iso() -> None:
    assert iso(None) is None and iso(pd.NaT) is None
    assert iso(pd.Timestamp("2026-10-01T08:00:00+02:00")) == "2026-10-01T06:00:00Z"
    assert iso(pd.Timestamp("2026-10-01T06:00:00")) == "2026-10-01T06:00:00Z"


def test_csv_neutralises_formulas() -> None:
    text = episodes_csv([ep(team="=HYPERLINK(1)", attribute=None)])
    lines = text.splitlines()
    assert lines[0].startswith("start,resolvedAt,address")
    assert "'=HYPERLINK(1)" in lines[1] and ",," in lines[1]


def test_run_records_keep_the_last_run_of_each_day_per_stream() -> None:
    from datetime import UTC, datetime

    from driftpilot.models import RunRecord

    def make(hour: int, managed: int, repo: str = "a") -> RunRecord:
        return RunRecord(
            run_id=f"{repo}{hour}", timestamp=datetime(2026, 10, 1, hour, tzinfo=UTC),
            working_dir="/x/infra", finding_count=0, critical_count=0, distinct_resources=0,
            unmanaged_count=1, noise_count=0, managed_resource_count=managed, repo=repo,
        )  # fmt: skip

    from driftpilot.report.dashboard.data import run_records

    rows = run_records([make(6, 10), make(12, 11), make(18, 12), make(7, 5, "b")])
    assert [(r["repo"], r["managed"], r["dir"]) for r in rows] == [
        ("b", 5, "infra"),
        ("a", 12, "infra"),
    ]


# --- action links, drawer fields and guardrail data ---


def test_only_plain_github_links_survive() -> None:
    from driftpilot.report.dashboard.data import safe_github_url

    good = "https://github.com/acme/infra/pull/7"
    assert safe_github_url(good) == good
    for bad in (
        "javascript:alert(1)", "data:text/html,<script>1</script>", "http://github.com/a/b",
        "https://github.com.evil.io/a", "https://evil.io/github.com/a", "https://u:p@github.com/a",
        "https://github.com:8443/a", 'https://github.com/a"onmouseover=x', "https://github.com/a b",
        "//github.com/a", "", None, 42,
    ):  # fmt: skip
        assert safe_github_url(bad) is None, bad


def frame_row(**kw) -> pd.DataFrame:
    base = {
        "finding_id": "f", "address": "docker_container.app3", "attribute": "memory",
        "resource_type": "docker_container", "start": pd.Timestamp("2026-10-01T06:00:00Z"),
        "end": pd.Timestamp("2026-10-01T06:00:00Z"), "resolved_at": pd.NaT, "runs_seen": 1,
        "severity": "high", "category": "security", "action": "revert", "source": "llm",
        "outcome": "pending", "resolved": False, "team": "t", "repo": "acme/infra",
        "environment": "prod", "account": "unknown", "drift_type": "infrastructure",
        "reason": "memory changed on docker_container.app3", "controls": ["least-privilege"],
        "guardrails": ["never-soften"], "confidence": 0.9, "rule_id": None,
        "prompt_version": "triage-v4", "pr_url": "javascript:alert(1)",
        "issue_url": "https://github.com/acme/infra/issues/3", "before": 512, "after": 1024,
    }  # fmt: skip
    return pd.DataFrame([base | kw])


def test_episode_records_carry_drawer_fields_and_drop_bad_links() -> None:
    [rec] = episode_records(frame_row())
    assert rec["prUrl"] is None  # javascript: dropped
    assert rec["issueUrl"] == "https://github.com/acme/infra/issues/3"
    assert rec["controls"] == ["least-privilege"] and rec["guardrails"] == ["never-soften"]
    assert rec["promptVersion"] == "triage-v4" and rec["confidence"] == 0.9
    assert rec["before"] == "512" and rec["after"] == "1024"
    assert "terraform apply -target=docker_container.app3" in rec["fix"]
    json.dumps(rec)


def test_suggested_fix_only_for_revert_and_never_names_hidden_addresses() -> None:
    [keep] = episode_records(frame_row(action="codify"))
    assert keep["fix"] is None
    [hidden] = episode_records(frame_row(), publish_addresses=False)
    assert "app3" not in json.dumps(hidden)
    [db] = episode_records(frame_row(address="postgres.public.users", drift_type="database"))
    assert db["fix"].startswith("-- Review first") and "never changes a database" in db["fix"]


def test_a_hostile_address_is_quoted_in_the_suggested_command() -> None:
    [rec] = episode_records(frame_row(address="x; rm -rf ~"))
    assert "-target='x; rm -rf ~'" in rec["fix"]


def test_links_default_to_history_and_drop_bad_values() -> None:
    from driftpilot.config import DashboardLinks
    from driftpilot.report.dashboard.data import build_links

    eps = [ep(repo="acme/infra"), ep(repo="acme/infra"), ep(repo="acme/db"), ep(repo="unknown")]
    assert build_links(None, eps) == {
        "repo": "acme/infra", "workflow": "driftpilot.yml", "branch": "main"
    }  # fmt: skip
    mine = DashboardLinks(repo="o/r", workflow="scan.yaml", branch="release/1")
    assert build_links(mine, eps) == {"repo": "o/r", "workflow": "scan.yaml", "branch": "release/1"}
    bad = DashboardLinks(repo="a/b/../c", workflow="x y.yml", branch="a..b")
    assert build_links(bad, []) == {"repo": None, "workflow": None, "branch": None}
    assert build_links(None, [ep(repo="unknown")])["repo"] is None


def test_guardrail_data_counts_calls_and_events() -> None:
    from datetime import UTC, datetime

    from driftpilot.models import AuditRecord, GuardrailEvent, RunRecord
    from driftpilot.report.dashboard.data import guardrail_data

    t = datetime(2026, 10, 1, tzinfo=UTC)
    runs = [
        RunRecord(
            run_id="r1", timestamp=t, working_dir="x", finding_count=0, critical_count=0,
            distinct_resources=0, unmanaged_count=0, noise_count=0, repo="acme/infra",
        )
    ]  # fmt: skip
    audit = [
        AuditRecord(timestamp=t, run_id="r1", purpose="triage", model="m", prompt_sha256="a",
                    valid=True, guardrail_events=[GuardrailEvent(kind="never-soften")]),
        AuditRecord(timestamp=t, run_id="r1", purpose="triage", model="m", prompt_sha256="b"),
    ]  # fmt: skip
    data = guardrail_data(audit, runs, 60)
    assert data["hasAudit"] and data["llmCallLimit"] == 60
    [row] = data["runs"]
    assert row["calls"] == 2 and row["invalid"] == 1 and row["events"] == {"never-soften": 1}
    assert row["repo"] == "acme/infra"
    assert guardrail_data(None, runs, None) == {"llmCallLimit": None, "hasAudit": False, "runs": []}


# ---- scan health (data.json "scans") and SLA ----


def _run_record(hour: int, errors: int = 0, repo="acme/infra", findings=1, working_dir="infra"):
    from datetime import UTC, datetime, timedelta

    from driftpilot.models import RunRecord

    return RunRecord(
        run_id=f"r{hour}-{repo}", timestamp=datetime(2026, 10, 1, tzinfo=UTC) + timedelta(hours=hour),
        working_dir=working_dir, finding_count=findings, critical_count=0, distinct_resources=1,
        unmanaged_count=0, noise_count=2, repo=repo, errors=errors,
    )  # fmt: skip


def test_old_run_lines_load_without_errors_field() -> None:
    from driftpilot.models import RunRecord

    line = (
        '{"run_id":"a","timestamp":"2026-10-01T00:00:00Z","working_dir":".","finding_count":0,'
        '"critical_count":0,"distinct_resources":0,"unmanaged_count":0,"noise_count":0}'
    )
    assert RunRecord.model_validate_json(line).errors == 0


def test_scan_health_counts_runs_gaps_and_errors_per_stream() -> None:
    from datetime import UTC, datetime, timedelta

    from driftpilot.report.dashboard.data import scan_health

    runs = [_run_record(h, errors=1 if h == 12 else 0) for h in (0, 6, 12, 36, 42)]
    runs.append(_run_record(40, repo="acme/db"))
    as_of = datetime(2026, 10, 1, 20, tzinfo=UTC) + timedelta(days=1)  # hour 44
    health = scan_health(runs, as_of, 6)
    assert health["expectedHours"] == 6
    infra = next(s for s in health["streams"] if s["repo"] == "acme/infra")
    assert infra["lastRun"] == "2026-10-02T18:00:00Z"
    assert infra["runCount24h"] == 2  # 36 h and 42 h (the window is the 24 h before 44 h)
    assert infra["runCount7d"] == 5
    assert infra["longestGapHours7d"] == 24  # 12 h -> 36 h
    assert infra["errors7d"] == 1
    assert [r["t"] for r in infra["recent"]][-1] == "2026-10-02T18:00:00Z"
    assert infra["recent"][2]["errors"] == 1 and infra["recent"][0]["noise"] == 2
    assert len(health["streams"]) == 2


def test_scan_health_lists_only_the_last_20_runs_and_handles_no_runs() -> None:
    from datetime import UTC, datetime

    from driftpilot.report.dashboard.data import scan_health

    runs = [_run_record(h) for h in range(30)]
    streams = scan_health(runs, datetime(2026, 10, 3, tzinfo=UTC), 6)["streams"]
    assert len(streams[0]["recent"]) == 20 and streams[0]["runCount7d"] == 30
    assert scan_health([], None, 6) == {"expectedHours": 6, "streams": []}


def test_scan_health_gap_includes_the_time_since_the_last_run() -> None:
    from datetime import UTC, datetime

    from driftpilot.report.dashboard.data import scan_health

    runs = [_run_record(0), _run_record(6)]
    other = [_run_record(60, repo="acme/db")]  # a stream that kept running
    streams = scan_health([*runs, *other], datetime(2026, 10, 3, 12, tzinfo=UTC), 6)["streams"]
    stale = next(s for s in streams if s["repo"] == "acme/infra")
    assert stale["longestGapHours7d"] == 54  # hour 6 until hour 60 (as of = newest run)


def test_build_data_has_scans_sla_and_settings() -> None:
    from driftpilot.history.analytics import analyze, episodes_frame
    from driftpilot.history.verdict_monitor import monitor
    from driftpilot.report.dashboard.data import build_data

    runs = [_run_record(0), _run_record(6)]
    report = analyze([], runs)
    eps = episodes_frame([], runs)
    data = build_data(report, monitor(eps, report.period_end), eps, runs, scan_every_hours=4)
    assert data["scans"]["expectedHours"] == 4 and len(data["scans"]["streams"]) == 1
    assert data["sla"] == {"critical": 24, "high": 72, "medium": 168, "low": None}
    data = build_data(report, monitor(eps, report.period_end), eps, runs, sla_hours={"high": 1})
    assert data["sla"] == {"high": 1}


def test_config_defaults_and_partial_sla_override(tmp_path) -> None:
    from driftpilot.config import load_config

    cfg = load_config(None, tmp_path)
    assert cfg.dashboard.scan_every_hours == 6
    assert cfg.dashboard.sla_hours == {"critical": 24, "high": 72, "medium": 168, "low": None}
    assert cfg.notifications.format == "slack" and cfg.notifications.min_severity == "high"
    (tmp_path / ".driftpilot.yml").write_text(
        "dashboard:\n  scan_every_hours: 1\n  sla_hours: {critical: 4, low: 720}\n"
    )
    cfg = load_config(None, tmp_path)
    assert cfg.dashboard.scan_every_hours == 1
    assert cfg.dashboard.sla_hours == {"critical": 4, "high": 72, "medium": 168, "low": 720}
