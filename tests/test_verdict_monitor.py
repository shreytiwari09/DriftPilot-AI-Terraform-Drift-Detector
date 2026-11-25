from datetime import UTC, datetime, timedelta

import pandas as pd

from driftpilot.history.verdict_monitor import alert_issue_body, monitor, monitor_streams

NOW = datetime(2026, 10, 25, tzinfo=UTC)


def frame(rows) -> pd.DataFrame:
    """rows: (days_ago, outcome, severity, action)."""
    return pd.DataFrame(
        [
            {"start": NOW - timedelta(days=d), "outcome": o, "severity": s, "action": a}
            for d, o, s, a in rows
        ]
    )


def steady(days_range, overruled_every=10, severity="medium"):
    return [
        (d, "overruled" if i % overruled_every == 0 else "accepted", severity, "codify")
        for i, d in enumerate(days_range)
    ]


def test_no_alert_when_stable() -> None:
    eps = frame(steady(range(1, 70)))
    report = monitor(eps, NOW)
    assert not report.breached
    assert report.recent_overrule_rate < 0.25


def test_overrule_rise_alerts() -> None:
    eps = frame(steady(range(15, 70)) + steady(range(1, 14), overruled_every=2))
    report = monitor(eps, NOW)
    assert report.breached
    assert "overruled" in report.alerts[0]
    assert report.baseline_overrule_rate < report.recent_overrule_rate
    assert "Recommended" in alert_issue_body(report)


def test_verdict_mix_shift_alerts() -> None:
    eps = frame(steady(range(15, 70)) + steady(range(1, 14), severity="critical"))
    report = monitor(eps, NOW)
    assert report.verdict_psi["severity"] > 0.25
    assert any("verdict severity values shifted" in a for a in report.alerts)


def test_too_few_decisions_no_alert() -> None:
    eps = frame([(1, "overruled", "low", "codify"), (2, "overruled", "low", "codify")])
    assert not monitor(eps, NOW).breached


def test_mix_shift_needs_enough_recent_episodes() -> None:
    """Live false alarm: one new episode in two weeks made PSI 4.6 on a mix of one."""
    eps = frame(steady(range(15, 70)) + [(3, "pending", "critical", "revert")])
    report = monitor(eps, NOW)
    assert report.verdict_psi["action"] > 0.25  # still reported on the dashboard
    assert not report.breached  # but too few episodes to call it a shift


def test_empty() -> None:
    assert not monitor(pd.DataFrame(), NOW).breached


def stream(repo: str, drift_type: str, rows) -> pd.DataFrame:
    return frame(rows).assign(repo=repo, drift_type=drift_type)


def test_a_new_stream_does_not_look_like_a_mix_shift_in_the_old_one() -> None:
    """Live false alarm: critical-heavy demo repos were pooled with the old history."""
    old = stream("org/infra", "infrastructure", steady(range(15, 70)))
    demo = stream("org/demo", "database", steady(range(1, 8), severity="critical"))
    pooled = pd.concat([old, demo], ignore_index=True)
    assert monitor(pooled, NOW).breached  # pooling the streams shifts the mix
    assert not monitor_streams(pooled, NOW).breached  # each stream on its own is steady


def test_mix_shift_inside_one_stream_still_alerts_and_names_it() -> None:
    eps = stream(
        "org/infra", "infrastructure",
        steady(range(15, 70)) + steady(range(1, 14), severity="critical"),
    )  # fmt: skip
    report = monitor_streams(eps, NOW)
    assert any("org/infra (infrastructure)" in a and "severity" in a for a in report.alerts)


def test_overrule_rate_is_still_checked_across_all_streams() -> None:
    a = stream(
        "org/a", "infrastructure", steady(range(15, 70)) + steady(range(1, 6), overruled_every=1)
    )
    b = stream("org/b", "database", steady(range(1, 6), overruled_every=1))
    report = monitor_streams(pd.concat([a, b], ignore_index=True), NOW)
    assert any("overruled" in x for x in report.alerts)
