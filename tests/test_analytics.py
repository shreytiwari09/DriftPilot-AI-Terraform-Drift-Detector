from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from driftpilot.history.analytics import (
    change_points,
    episodes_frame,
    health,
    psi,
    recurring,
    zscore_anomalies,
)
from driftpilot.models import DriftFinding, HistoryEvent, RunRecord, Verdict

T0 = datetime(2026, 10, 1, tzinfo=UTC)


def run(i: int, findings: int = 0) -> RunRecord:
    return RunRecord(
        run_id=f"r{i}",
        timestamp=T0 + timedelta(hours=6 * i),
        working_dir="w",
        finding_count=findings,
        critical_count=0,
        distinct_resources=findings,
        unmanaged_count=0,
        noise_count=0,
        managed_resource_count=10,
    )


def event(i: int, after=1, address="t.a", outcome="pending") -> HistoryEvent:
    f = DriftFinding(
        id=f"id-{address}",
        run_id=f"r{i}",
        detected_at=T0,
        provider="p",
        resource_type="t",
        address=address,
        change_kind="modified",
        attribute_path="x",
        before=0,
        after=after,
    )
    v = Verdict(
        finding_id=f.id,
        source="llm",
        is_real_drift=True,
        severity="medium",
        category="availability",
        intent="unknown",
        recommended_action="codify",
        confidence=0.9,
        reason="r",
    )
    return HistoryEvent(
        run_id=f"r{i}",
        timestamp=T0 + timedelta(hours=6 * i),
        finding=f,
        verdict=v,
        human_outcome=outcome,
    )


def test_consecutive_detections_are_one_episode() -> None:
    runs = [run(i) for i in range(10)]
    # seen in runs 1-3 (one episode), gone in 4, back in 5 (new), value changes in 6 (new)
    events = [event(1), event(2), event(3), event(5), event(6, after=2)]
    eps = episodes_frame(events, runs)
    assert eps["runs_seen"].tolist() == [3, 1, 1]
    assert eps["resolved"].tolist() == [True, True, True]


def test_unresolved_when_still_present_in_last_run() -> None:
    runs = [run(i) for i in range(3)]
    eps = episodes_frame([event(1), event(2)], runs)
    assert eps["resolved"].tolist() == [False]


def test_recurring_needs_three_episodes_in_window() -> None:
    runs = [run(i) for i in range(20)]
    events = [event(i) for i in (2, 6, 10)] + [event(i, address="t.b") for i in (2, 3, 4, 5)]
    found = recurring(episodes_frame(events, runs), now=T0 + timedelta(days=5))
    assert [(r.address, r.episodes) for r in found] == [("t.a", 3)]  # t.b is one long episode


def test_zscore_flags_only_the_spike() -> None:
    days = pd.date_range("2026-08-01", periods=40, freq="D").date
    counts = pd.Series([1, 2] * 20, index=days)
    counts.iloc[30] = 15
    anomalies = zscore_anomalies(counts)
    assert [a.day for a in anomalies] == [days[30]]


def test_change_point_at_level_shift() -> None:
    days = pd.date_range("2026-08-01", periods=40, freq="D").date
    counts = pd.Series([1, 2] * 10 + [8, 9] * 10, index=days)
    assert change_points(counts) == [days[20]]


def test_psi() -> None:
    same = pd.Series({"low": 50, "high": 50})
    assert psi(same, same) == pytest.approx(0)
    assert psi(same, pd.Series({"low": 10, "high": 90})) > 0.25


def test_health() -> None:
    runs = [run(0, 0), run(1, 1), run(2, 1), run(3, 0)]
    eps = episodes_frame([event(1), event(2)], runs)
    h = health(eps, runs)
    assert (h.pct_runs_zero_drift, h.mean_hours_to_remediate, h.pct_resources_ever_drifted) == (
        50.0,
        6.0,
        10.0,
    )


def test_empty_history() -> None:
    assert episodes_frame([], []).empty
    assert health(episodes_frame([], []), []).runs == 0
