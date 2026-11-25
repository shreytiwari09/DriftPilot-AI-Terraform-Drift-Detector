"""The evaluation summary the Guardrails page shows must match the saved results files."""

import importlib.util
import json
from pathlib import Path

from driftpilot.report.dashboard.data import evaluation_summary

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location(
    "export_eval_summary", ROOT / "scripts/export_eval_summary.py"
)
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)


def test_shipped_summary_loads_and_is_up_to_date() -> None:
    shipped = evaluation_summary()
    assert shipped is not None, "run scripts/export_eval_summary.py"
    assert shipped == json.loads(json.dumps(export.build())), "stale: re-run the export script"


def test_numbers_match_the_results_files() -> None:
    s = evaluation_summary()
    results = ROOT / "eval/results"
    adv = json.loads((results / "adversarial.json").read_text())
    off, on = adv[0], adv[1]
    assert s["adversarial"]["withoutGuardrails"]["attackSuccess"] == {
        "hits": off["attack_stats"]["all"][0],
        "total": off["attack_stats"]["all"][1],
    }
    assert s["adversarial"]["withGuardrails"]["neverSoften"]["hits"] == 0
    assert (
        s["adversarial"]["withGuardrails"]["neverSoften"]["total"]
        == (on["attack_stats"]["never_soften"][1])
    )
    assert s["adversarial"]["cases"] == 24 and s["adversarial"]["benignCases"] == 4
    main = json.loads((results / "results.json").read_text())
    assert s["model"] == main["model"]
    cloud = next(r for r in s["main"]["setups"] if r["setup"] == "rules + cloud LLM")
    want = next(x for x in main["setups"] if x["setup"] == "rules + cloud LLM")["metrics"]
    assert cloud["severityRight"] == want["severity_accuracy"]
    db = json.loads((results / "database.json").read_text())
    assert [r["setup"] for r in s["database"]["setups"]] == [x["setup"] for x in db]
    assert s["date"] == "2026-11-24"


def test_the_page_summary_numbers_equal_the_markdown_table() -> None:
    table = (ROOT / "eval/results/adversarial.md").read_text()
    s = evaluation_summary()["adversarial"]
    off, on = s["withoutGuardrails"], s["withGuardrails"]
    assert f"{off['attackSuccess']['hits']}/{off['attackSuccess']['total']}" in table
    assert f"{on['softerOnly']['hits']}/{on['softerOnly']['total']} (8%)" in table
    assert f"{on['benignRight']['hits']}/{on['benignRight']['total']} (50%)" in table


def test_build_data_carries_the_evaluation() -> None:
    from driftpilot.history.analytics import analyze, episodes_frame
    from driftpilot.history.verdict_monitor import monitor
    from driftpilot.report.dashboard.data import build_data

    report = analyze([], [])
    eps = episodes_frame([], [])
    data = build_data(report, monitor(eps, report.period_end), eps, [])
    assert data["evaluation"]["adversarial"]["cases"] == 24
