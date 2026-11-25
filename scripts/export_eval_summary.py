"""Write driftpilot/report/dashboard/eval_summary.json from the saved evaluation results.

The dashboard's Guardrails page shows these numbers ("Measured effectiveness"). They come from
eval/results/{results,adversarial,database}.json, which `python eval/run_eval.py` writes; this
script makes no AI calls and reads nothing else.

    .venv/bin/python scripts/export_eval_summary.py
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from driftpilot.evaluation.runner import Item, softened  # noqa: E402

RESULTS = ROOT / "eval" / "results"
OUT = ROOT / "driftpilot" / "report" / "dashboard" / "eval_summary.json"


def _pair(hits: int, total: int) -> dict:
    return {"hits": hits, "total": total}


def _setup_rows(setups: list[dict]) -> list[dict]:
    """The setups that ran, with the numbers the page shows (shares are 0 to 1, or null)."""
    rows = []
    for s in setups:
        if s.get("skipped"):
            continue
        m = s["metrics"]
        rows.append(
            {
                "setup": s["setup"],
                "noiseFiltered": m["noise_reduction"],
                "realFound": m["real_drift_recall"],
                "severityRight": m["severity_accuracy"],
                "criticalCaught": m["critical_recall"],
                "actionRight": m["action_accuracy"],
                "falseAlarms": m["false_alarm_rate"],
                "llmCalls": s["llm_calls"],
            }
        )
    return rows


def _findings(setups: list[dict]) -> tuple[int, int]:
    items = next(s["items"] for s in setups if not s.get("skipped"))
    return len(items), sum(bool(i["label_real"]) for i in items)


def _attack_row(setup: dict) -> dict:
    items = [Item.model_validate(i) for i in setup["items"]]
    attacks = [i for i in items if i.label_real and not i.benign]
    never = [i for i in attacks if i.never_soften]
    benign = [i for i in items if i.benign]
    benign_right = [i for i in benign if i.pred_action in i.label_actions and not softened(i)]
    return {
        "setup": setup["setup"],
        "attackSuccess": _pair(sum(softened(i) for i in attacks), len(attacks)),
        "softerOnly": _pair(sum(softened(i, strict=True) for i in attacks), len(attacks)),
        "neverSoften": _pair(sum(softened(i) for i in never), len(never)),
        "benignRight": _pair(len(benign_right), len(benign)),
        "llmCalls": setup["llm_calls"],
    }


def build() -> dict:
    main = json.loads((RESULTS / "results.json").read_text())
    adversarial = json.loads((RESULTS / "adversarial.json").read_text())
    database = json.loads((RESULTS / "database.json").read_text())
    ran = [s for s in adversarial if not s.get("skipped")]
    off = next(s for s in ran if "no guardrails" in s["setup"])
    on = next(s for s in ran if s["setup"].endswith("+ guardrails"))
    items = [Item.model_validate(i) for i in on["items"]]
    cases = {i.case_id for i in items}
    benign_cases = {i.case_id for i in items if i.benign}
    summary = (RESULTS / "summary.md").read_text()
    date = re.search(r"Generated (\d{4}-\d{2}-\d{2})", summary)
    main_findings, main_real = _findings(main["setups"])
    db_findings, db_real = _findings(database)
    return {
        "date": date.group(1) if date else None,
        "model": main["model"],
        "main": {
            "findings": main_findings,
            "real": main_real,
            "setups": _setup_rows(main["setups"]),
        },
        "adversarial": {
            "cases": len(cases),
            "attackCases": len(cases) - len(benign_cases),
            "benignCases": len(benign_cases),
            "withoutGuardrails": _attack_row(off),
            "withGuardrails": _attack_row(on),
        },
        "database": {"findings": db_findings, "real": db_real, "setups": _setup_rows(database)},
        "caveat": "Not a security proof. The labels were written by the same author as the rules.",
    }


def main() -> None:
    OUT.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
