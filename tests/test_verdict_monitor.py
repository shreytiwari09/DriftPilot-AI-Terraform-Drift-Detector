from datetime import UTC, datetime, timedelta

import pandas as pd

from driftpilot.history.verdict_monitor import alert_issue_body, monitor

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


def test_empty() -> None:
    assert not monitor(pd.DataFrame(), NOW).breached
