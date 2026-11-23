import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from driftpilot.history.analytics import analyze, episodes_frame
from driftpilot.history.verdict_monitor import monitor
from driftpilot.models import Context
from driftpilot.report.dashboard import CHART_JS, build_dashboard
from driftpilot.report.dashboard.data import compute_kpis, episode_records, episodes_csv

SCRIPT = Path(__file__).parents[1] / "scripts" / "simulate_history.py"
spec = importlib.util.spec_from_file_location("simulate_history", SCRIPT)
sim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sim)

EVENTS, RUNS = sim.simulate(seed=7, split=True)


def files_for(events, runs, **kwargs) -> dict[str, str]:
    report = analyze(events, runs)
    eps = episodes_frame(events, runs)
    return build_dashboard(report, monitor(eps, report.period_end), eps, runs, **kwargs)


def absent(text: str, needle: str) -> None:
    """`needle not in text`, without pytest trying to print a huge page when it fails."""
    if needle in text:
        pytest.fail(f"{needle!r} found in the output")


def embedded(page: str) -> dict:
    match = re.search(
        r'<script id="embedded-data" type="application/json">(.*?)</script>', page, re.S
    )
    return json.loads(match.group(1))


def test_page_and_data_json_carry_the_same_data() -> None:
    files = files_for(EVENTS, RUNS, title="Sim <demo>", note="Simulated <history>")
    assert set(files) == {"index.html", "data.json"}
    data = json.loads(files["data.json"])
    assert embedded(files["index.html"]) == data
    assert data["schema"] == 1 and data["note"] == "Simulated <history>"
    assert "<title>Sim &lt;demo&gt;</title>" in files["index.html"]
    assert not re.search(r"__[A-Z_]+__", files["index.html"])  # every placeholder filled
    assert len(data["analytics"]["days"]) == len(data["analytics"]["daily"]) == 90
    assert data["analytics"]["changePoints"] and data["monitor"]["alerts"]


def test_data_has_what_the_filters_need() -> None:
    data = json.loads(files_for(EVENTS, RUNS)["data.json"])
    eps = data["episodes"]
    assert {e["driftType"] for e in eps} == {"infrastructure", "database"}
    assert {e["environment"] for e in eps} == {"prod", "staging", "dev"}
    assert len({e["team"] for e in eps}) >= 4 and len({e["repo"] for e in eps}) == 3
    assert {e["severity"] for e in eps} >= {"critical", "high", "medium", "low"}
    assert {e["decidedBy"] for e in eps} == {"rule", "llm"}
    assert {e["outcome"] for e in eps} == {"accepted", "overruled"}
    assert all(e["resolvedAt"] for e in eps if e["resolved"])
    assert {r["repo"] for r in data["runs"]} == {e["repo"] for e in eps}
    k = data["kpis"]
    assert k["iacCoverage"] == pytest.approx(100 * 60 / 64, abs=0.1)  # 60 managed, 4 outside
    assert k["driftRate"] and k["mttrHours"] and k["recurringOffenders"] >= 1
    assert k["episodes"] == len(eps) == data["analytics"].get("episodes", len(eps))


def test_account_ids_and_arns_never_reach_the_files() -> None:
    files = files_for(EVENTS, RUNS)
    text = re.sub(r'"id": "[0-9a-f]{12}"', "", files["index.html"] + files["data.json"])
    assert re.search(r"(?<!\d)\d{12}(?!\d)", text) is None  # (finding ids are hashes)
    assert "************" in text  # the masked accounts


def test_publish_addresses_off_hides_resource_names() -> None:
    shown = files_for(EVENTS, RUNS)["data.json"]
    hidden = files_for(EVENTS, RUNS, publish_addresses=False)
    assert "docker_container.app3" in shown
    for text in hidden.values():
        for name in ("app3", "svc0", "postgres.public", "github_repository.svc"):
            absent(text, name)
    data = json.loads(hidden["data.json"])
    assert data["publishAddresses"] is False
    assert data["analytics"]["recurring"][0]["address"].startswith("resource-")
    assert data["kpis"]["driftedResources"] == json.loads(shown)["kpis"]["driftedResources"]


def test_hostile_text_cannot_break_out_of_the_page() -> None:
    evil = "</script><script>alert(1)</script>"
    events = [e.model_copy(deep=True) for e in EVENTS[:20]]
    for e in events:
        e.context = Context(team=evil, repo=evil, environment=evil)
    page = files_for(events, RUNS)["index.html"]
    absent(page, evil)
    absent(page, "alert(1)</script>")
    assert embedded(page)["episodes"][0]["team"] == evil
    absent(page, "innerHTML")  # the page sets text with textContent only


def test_page_has_no_dependency_besides_chartjs() -> None:
    page = files_for(EVENTS, RUNS)["index.html"]
    assert set(re.findall(r"https?://[^\s\"'<>)]+", page)) == {CHART_JS}
    assert "4.4.1" in CHART_JS
    for control in ("f-from", "f-to", "f-team", "f-repo", "f-environment", "f-driftType",
                    "f-severity", "f-status", "f-decidedBy", "f-outcome", "f-search"):  # fmt: skip
        assert f'id="{control}"' in page
    for label in ("IaC coverage", "Drift rate", "AWS Well-Architected metric", "DriftPilot metric"):
        assert label in page
    assert 'fetch("data.json"' in page and "5 * 60 * 1000" in page


def test_dashboard_with_no_history() -> None:
    files = files_for([], [])
    data = json.loads(files["data.json"])
    assert data["episodes"] == [] and data["runs"] == [] and data["kpis"]["iacCoverage"] is None
    assert "<canvas" in files["index.html"]


def test_old_history_without_context_still_builds_a_dashboard() -> None:
    old = [e.model_copy(update={"context": Context()}) for e in EVENTS]
    plain = {"repo": "unknown", "environment": "unknown", "drift_type": "infrastructure"}
    old_runs = [r.model_copy(update=plain) for r in RUNS]
    data = json.loads(files_for(old, old_runs)["data.json"])
    assert {e["team"] for e in data["episodes"]} == {"unowned"}
    assert {e["repo"] for e in data["episodes"]} == {"unknown"}


# --- The page's JavaScript must give the same answers as the Python reference (needs node). ---

NODE = shutil.which("node")
FILTERS = [
    {}, {"team": "payments"}, {"repo": "driftpilot-demo/database"}, {"environment": "staging"},
    {"driftType": "database"}, {"severity": "critical"}, {"status": "open"},
    {"status": "resolved", "decidedBy": "rule"}, {"outcome": "overruled"},
    {"from": "2026-09-01", "to": "2026-09-30"}, {"search": "APP3"},
    {"team": "platform", "environment": "prod", "from": "2026-08-15"}, {"team": "nobody"},
]  # fmt: skip


def run_js(tmp_path: Path, page: str, input_data: dict, body: str):
    logic = re.search(r'<script id="logic">(.*?)</script>', page, re.S).group(1)
    script = tmp_path / "logic.js"
    script.write_text(
        logic + "\nconst input = JSON.parse(require('fs').readFileSync(0, 'utf8'));\n" + body
    )
    done = subprocess.run(
        [NODE, str(script)],
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_javascript_kpis_match_python(tmp_path: Path) -> None:
    files = files_for(EVENTS, RUNS)
    data = json.loads(files["data.json"])
    out = run_js(
        tmp_path,
        files["index.html"],
        {"data": data, "filters": FILTERS},
        "const d = input.data; console.log(JSON.stringify(input.filters.map("
        "(f) => computeKpis(d.episodes, d.runs, f, d.asOf))));",
    )
    for f, js in zip(FILTERS, json.loads(out), strict=True):
        py = compute_kpis(data["episodes"], data["runs"], f, data["asOf"])
        assert js.keys() == py.keys()
        for key, value in py.items():
            if value is None or js[key] is None:
                assert js[key] == value, (f, key)
            else:
                assert js[key] == pytest.approx(value, abs=0.11), (f, key)
    teams = [py for f in FILTERS if f.get("team") == "payments"]
    assert teams  # the per-team denominators were exercised


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_javascript_csv_matches_python(tmp_path: Path) -> None:
    files = files_for(EVENTS, RUNS)
    rows = json.loads(files["data.json"])["episodes"][:30]
    rows[0] = rows[0] | {"team": '=cmd|"x", y', "attribute": None}
    out = run_js(
        tmp_path,
        files["index.html"],
        {"rows": rows},
        "process.stdout.write(episodesCsv(input.rows));",
    )
    assert out == episodes_csv(rows)


def test_episode_records_round_trip_through_json() -> None:
    eps = episodes_frame(EVENTS, RUNS)
    records = episode_records(eps)
    assert json.loads(json.dumps(records)) == records
