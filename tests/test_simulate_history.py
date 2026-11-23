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
