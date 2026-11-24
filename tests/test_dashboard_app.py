"""The React dashboard as the Python side ships it: app, data.json, embedded data, fallback."""

import importlib.util
import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from driftpilot import cli
from driftpilot.history.analytics import analyze, episodes_frame
from driftpilot.history.learn import publish_dashboard
from driftpilot.history.store import LocalStore
from driftpilot.history.verdict_monitor import monitor
from driftpilot.models import Context
from driftpilot.report import dashboard as dash
from driftpilot.report.dashboard import app_files, build_site

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location(
    "simulate_history", ROOT / "scripts/simulate_history.py"
)
sim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sim)
EVENTS, RUNS = sim.simulate(seed=7, split=True)
AUDIT = sim.simulate_audit(EVENTS, RUNS)


def site(events=EVENTS, runs=RUNS, **kw) -> dict[str, str]:
    report = analyze(events, runs)
    eps = episodes_frame(events, runs)
    return build_site(report, monitor(eps, report.period_end), eps, runs, audit=AUDIT, **kw)


def embedded(page: str) -> dict:
    m = re.search(r'<script id="embedded-data" type="application/json">(.*?)</script>', page, re.S)
    return json.loads(m.group(1))


def test_the_built_app_ships_with_the_package() -> None:
    app = app_files()
    assert app is not None, "run `npm run build:app` in dashboard/"
    assert "index.html" in app and any(p.startswith("assets/") and p.endswith(".js") for p in app)
    html = app["index.html"]
    assert "__DRIFTPILOT_DATA__" in html and "__DRIFTPILOT_TITLE__" in html


def test_app_page_works_from_disk_and_from_any_sub_path() -> None:
    html = app_files()["index.html"]
    assert 'type="module"' not in html and "crossorigin" not in html  # file:// refuses both
    for url in re.findall(r'(?:src|href)="([^"]+)"', html):
        assert url.startswith("./"), url  # relative, so a GitHub Pages sub-path works
    js = [p for p in app_files() if p.endswith(".js")]
    assert js  # the bundle is a classic script


def test_site_has_app_page_and_data_with_the_same_content() -> None:
    files = site(title="Sim <demo>")
    assert {"index.html", "data.json"} <= set(files) and any(p.startswith("assets/") for p in files)
    data = json.loads(files["data.json"])
    assert embedded(files["index.html"]) == data
    assert "<title>Sim &lt;demo&gt;</title>" in files["index.html"]
    assert not re.search(r"__DRIFTPILOT_[A-Z]+__", files["index.html"])
    assert data["episodes"] and data["guardrails"]["hasAudit"] and data["links"]["repo"]


def test_site_data_carries_drawer_guardrail_and_link_fields() -> None:
    data = json.loads(site()["data.json"])
    eps = data["episodes"]
    assert any(e["guardrails"] for e in eps) and any(e["controls"] for e in eps)
    assert all(e["reason"] for e in eps)
    assert any(e["fix"] for e in eps if e["action"] == "revert")
    assert all(e["fix"] is None for e in eps if e["action"] != "revert")
    for e in eps:
        for key in ("prUrl", "issueUrl"):
            assert e[key] is None or e[key].startswith("https://github.com/")
    assert data["guardrails"]["llmCallLimit"] == 60


def test_hostile_text_cannot_break_out_of_the_app_page() -> None:
    evil = "</script><script>alert(1)</script>"
    events = [e.model_copy(deep=True) for e in EVENTS[:20]]
    for e in events:
        e.context = Context(team=evil, repo=evil, environment=evil)
    page = site(events)["index.html"]
    assert evil not in page and "alert(1)</script>" not in page
    assert embedded(page)["episodes"][0]["team"] == evil


def test_account_ids_never_reach_the_site_files() -> None:
    files = site()
    text = re.sub(r'"id":\s*"[0-9a-f]{12}"', "", files["index.html"] + files["data.json"])
    assert re.search(r"(?<!\d)\d{12}(?!\d)", text) is None


def test_falls_back_to_the_single_file_page_when_the_app_is_missing() -> None:
    with patch.object(dash, "app_files", return_value=None):
        files = site()
    assert set(files) == {"index.html", "data.json"}
    assert "chart.umd.min.js" in files["index.html"]  # the older page


def test_a_hostile_link_in_history_is_dropped_before_publishing() -> None:
    events = [e.model_copy(deep=True) for e in EVENTS[:40]]
    for e in events:
        if e.remediation:
            e.remediation.pr_url = "javascript:alert(1)"
            e.remediation.issue_url = "https://evil.example/github.com/x"
    data = json.loads(site(events)["data.json"])
    assert all(e["prUrl"] is None and e["issueUrl"] is None for e in data["episodes"])
    assert "javascript:" not in site(events)["data.json"]


def test_react_fixture_is_up_to_date() -> None:
    """The vitest parity tests read dashboard/tests/fixtures/sim.json: regenerate it when stale."""
    spec = importlib.util.spec_from_file_location(
        "make_fixture", ROOT / "dashboard/scripts/make_fixture.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fixture = ROOT / "dashboard/tests/fixtures/sim.json"
    assert json.loads(fixture.read_text()) == json.loads(json.dumps(mod.build())), (
        "run `.venv/bin/python dashboard/scripts/make_fixture.py`"
    )


def test_react_source_never_writes_html_strings() -> None:
    src = ROOT / "dashboard/src"
    if not src.exists():
        return
    text = "\n".join(p.read_text() for p in src.rglob("*.ts*"))
    assert "dangerouslySetInnerHTML" not in text and "innerHTML" not in text
    assert "eval(" not in text


def test_publish_writes_the_nested_asset_files_too() -> None:
    not_found = type("NotFound", (Exception,), {"status": 404})
    repo = MagicMock(default_branch="main")
    repo.get_contents.side_effect = not_found()
    files = {"index.html": "<html>", "assets/app.js": "x", "data.json": "{}"}
    with patch("github.Github") as gh:
        gh.return_value.get_repo.return_value = repo
        publish_dashboard(files, "o/r", "t", "msg")
    assert [c.args[0] for c in repo.create_file.call_args_list] == list(files)


def test_report_html_writes_the_app_and_data(tmp_path: Path) -> None:
    LocalStore(tmp_path / "h").save(EVENTS, RUNS, "sim")
    out = tmp_path / "site"
    result = CliRunner().invoke(
        cli.app, ["report", "--history", str(tmp_path / "h"), "--html", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert (out / "index.html").exists() and (out / "data.json").exists()
    assert list((out / "assets").glob("*.js")) and list((out / "assets").glob("*.css"))
    assert embedded((out / "index.html").read_text()) == json.loads((out / "data.json").read_text())
