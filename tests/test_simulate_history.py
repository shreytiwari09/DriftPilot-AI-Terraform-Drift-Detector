import importlib.util
from datetime import timedelta
from pathlib import Path

from driftpilot.history.analytics import analyze, episodes_frame
from driftpilot.history.verdict_monitor import monitor

SCRIPT = Path(__file__).parents[1] / "scripts" / "simulate_history.py"
spec = importlib.util.spec_from_file_location("simulate_history", SCRIPT)
sim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sim)


def test_events_carry_teams_repos_environments_and_both_drift_types() -> None:
    events, _ = sim.simulate(seed=7)
    contexts = [e.context for e in events]
    assert {c.drift_type for c in contexts} == {"infrastructure", "database"}
    assert {c.environment for c in contexts} == {"prod", "staging", "dev"}
    assert {c.team for c in contexts} == {"payments", "platform", "security", "growth", "data"}
    assert len({c.repo for c in contexts}) == 3
    database = [e for e in events if e.context.drift_type == "database"]
    assert database and all(e.finding.address.startswith("postgres.") for e in database)
    assert all(e.finding.resource_type.startswith("pg_") for e in database)


def test_split_streams_still_show_every_planted_pattern() -> None:
    events, runs = sim.simulate(seed=7, split=True)
    assert len({(r.repo, r.environment) for r in runs}) == 5
    assert sum(r.managed_resource_count for r in runs[:5]) == sim.MANAGED_RESOURCES
    report = analyze(events, runs)
    spike = (report.period_start + timedelta(days=sim.SPIKE_DAY)).date()
    assert max(report.day_anomalies, key=lambda a: a.z).day == spike
    assert spike in report.change_points
    top = max(report.recurring, key=lambda r: r.episodes)
    assert (top.address, top.attribute) == sim.RECURRING
    assert monitor(episodes_frame(events, runs), report.period_end).breached


def test_both_modes_plant_the_same_episodes() -> None:
    single, _ = sim.simulate(seed=7)
    split, _ = sim.simulate(seed=7, split=True)
    assert len(single) == len(split)
    assert {e.finding.id for e in single} == {e.finding.id for e in split}


def test_simulated_audit_is_deterministic_and_has_guardrail_events() -> None:
    events, runs = sim.simulate(seed=7, split=True)
    audit = sim.simulate_audit(events, runs)
    assert audit and audit == sim.simulate_audit(events, runs)
    kinds = {g.kind for a in audit for g in a.guardrail_events}
    assert {"never-soften", "suspicious-input"} <= kinds
    per_run: dict[str, int] = {}
    for a in audit:
        per_run[a.run_id] = per_run.get(a.run_id, 0) + 1
    assert max(per_run.values()) <= 60  # inside the default budget


def test_simulated_scan_health_has_a_late_stream_and_some_errors() -> None:
    from driftpilot.report.dashboard.data import scan_health

    _, runs = sim.simulate(seed=7, split=True)
    health = scan_health(runs, max(r.timestamp for r in runs), 6)
    newest = max(r.timestamp for r in runs)
    last: dict[str, object] = {}
    for r in runs:
        last[r.repo + r.environment] = r.timestamp
    lag = {k: (newest - t).total_seconds() / 3600 for k, t in last.items()}
    late = [k for k, g in lag.items() if 6 * 1.5 < g <= 6 * 3]
    assert late == ["driftpilot-demo/databaseprod"]
    assert sum(r.errors for r in runs) >= 3
    assert any(s["errors7d"] for s in health["streams"])
    assert max(r.errors for r in runs) == 2


def test_adding_scan_health_did_not_move_the_planted_data() -> None:
    events, runs = sim.simulate(seed=7, split=True)
    assert len(events) == 667 and len(runs) == 1800 - sim.LATE_SLOTS
