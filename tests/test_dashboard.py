import importlib.util
import json
import re
from pathlib import Path

from driftpilot.history.analytics import analyze, episodes_frame
from driftpilot.history.verdict_monitor import monitor
from driftpilot.report.dashboard import build_dashboard

SCRIPT = Path(__file__).parents[1] / "scripts" / "simulate_history.py"
spec = importlib.util.spec_from_file_location("simulate_history", SCRIPT)
sim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sim)


def page_for(events, runs, **kwargs) -> str:
    report = analyze(events, runs)
    eps = episodes_frame(events, runs)
    return build_dashboard(report, monitor(eps, report.period_end), eps, **kwargs)


def test_dashboard_contains_data_and_findings() -> None:
    events, runs = sim.simulate(seed=7)
    page = page_for(events, runs, note="Simulated <history>")
    assert "$" not in re.sub(
        r"<script>.*?</script>", "", page, flags=re.S
    )  # all placeholders filled
    assert "Simulated &lt;history&gt;" in page  # escaped
    data = json.loads(re.search(r"const D = (\{.*?\});\n", page).group(1))
    assert len(data["days"]) == len(data["daily"]) == 90
    assert data["changePoints"]
    assert "docker_container.app3" in page
    assert "overruled" in page


def test_dashboard_with_no_history() -> None:
    page = page_for([], [])
    assert "None." in page and "<canvas" in page
