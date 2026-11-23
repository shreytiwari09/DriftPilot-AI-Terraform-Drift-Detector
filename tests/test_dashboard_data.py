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
