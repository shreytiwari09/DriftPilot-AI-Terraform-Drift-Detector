"""Phase 3 gate: on simulated history, analytics and the verdict monitor find what was planted."""

import importlib.util
from datetime import timedelta
from pathlib import Path

from driftpilot.history.analytics import analyze, episodes_frame
from driftpilot.history.verdict_monitor import monitor

SCRIPT = Path(__file__).parents[1] / "scripts" / "simulate_history.py"
spec = importlib.util.spec_from_file_location("simulate_history", SCRIPT)
sim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sim)

EVENTS, RUNS = sim.simulate(seed=7)
REPORT = analyze(EVENTS, RUNS)
SPIKE = (REPORT.period_start + timedelta(days=sim.SPIKE_DAY)).date()


def test_planted_spike_is_the_strongest_day_anomaly() -> None:
    strongest = max(REPORT.day_anomalies, key=lambda a: a.z)
    assert strongest.day == SPIKE


def test_isolation_forest_agrees_on_the_spike() -> None:
    days = [a.timestamp.date() for a in REPORT.run_anomalies]
    assert sum(d in (SPIKE, SPIKE + timedelta(days=1)) for d in days) > len(days) / 2


def test_change_point_at_the_spike() -> None:
    assert SPIKE in REPORT.change_points


def test_planted_recurring_pattern_is_top() -> None:
    top = max(REPORT.recurring, key=lambda r: r.episodes)
    assert (top.address, top.attribute) == sim.RECURRING


def test_verdict_monitor_flags_overrule_rise() -> None:
    report = monitor(episodes_frame(EVENTS, RUNS), REPORT.period_end)
    assert report.breached
    assert report.recent_overrule_rate > 2 * report.baseline_overrule_rate
    assert any("overruled" in a for a in report.alerts)


def test_severity_mix_shift_detected() -> None:
    by_dim = {s.dimension: s for s in REPORT.shifts}
    assert by_dim["severity"].shifted


def test_simulation_is_deterministic() -> None:
    events, runs = sim.simulate(seed=7)
    assert len(events) == len(EVENTS) and len(runs) == len(RUNS)
