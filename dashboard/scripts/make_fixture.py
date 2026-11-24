"""Write dashboard/tests/fixtures/sim.json: the simulated history (seed 7) as data.json, plus the
answers the Python code gives for a set of filters. The TypeScript tests must match them.

    .venv/bin/python dashboard/scripts/make_fixture.py
"""

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from driftpilot.history.analytics import analyze, episodes_frame  # noqa: E402
from driftpilot.history.verdict_monitor import monitor  # noqa: E402
from driftpilot.report.dashboard.data import build_data, compute_kpis, episodes_csv  # noqa: E402

FILTERS = [
    {}, {"team": "payments"}, {"team": "platform", "environment": "prod", "from": "2026-08-15"},
    {"repo": "driftpilot-demo/database"}, {"environment": "staging"}, {"driftType": "database"},
    {"severity": "critical"}, {"status": "open"}, {"status": "resolved", "decidedBy": "rule"},
    {"outcome": "overruled"}, {"outcome": "pending"}, {"from": "2026-09-01", "to": "2026-09-30"},
    {"search": "APP3"}, {"search": "  postgres "}, {"team": "nobody"},
    {"team": "data", "driftType": "database", "status": "open"},
    {"from": "2026-10-20"}, {"to": "2026-07-31"},
]  # fmt: skip


def build() -> dict:
    spec = importlib.util.spec_from_file_location(
        "simulate_history", ROOT / "scripts" / "simulate_history.py"
    )
    sim = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sim)
    events, runs = sim.simulate(seed=7, split=True)
    report = analyze(events, runs)
    episodes = episodes_frame(events, runs)
    data = build_data(report, monitor(episodes, report.period_end), episodes, runs,
                      audit=sim.simulate_audit(events, runs))  # fmt: skip
    data["generated"] = "2026-10-25T00:00:00Z"  # fixed, so the file only changes with the logic
    rows = data["episodes"][:40]
    rows[0] = rows[0] | {"team": '=cmd|"x", y', "attribute": None}
    rows[1] = rows[1] | {"address": "a,b\nc", "resolved": True}
    return {
        "data": data,
        "cases": [
            {"filters": f, "kpis": compute_kpis(data["episodes"], data["runs"], f, data["asOf"])}
            for f in FILTERS
        ],
        "csvRows": rows,
        "csv": episodes_csv(rows),
    }


if __name__ == "__main__":
    out = ROOT / "dashboard" / "tests" / "fixtures" / "sim.json"
    out.write_text(json.dumps(build(), separators=(",", ":"), sort_keys=True) + "\n")
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")
