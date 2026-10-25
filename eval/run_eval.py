"""Run the DriftPilot evaluation; write markdown tables to eval/results/ (SPEC §8).

    python eval/run_eval.py                 # all setups (cloud LLM: GEMINI_API_KEY, e.g. .env)
    python eval/run_eval.py --no-llm        # only the setups that need no LLM
    python eval/run_eval.py --stability 0   # skip the prompt-stability repeats

LLM answers are cached in eval/cache/, so re-running is free and gives the same tables. Delete the
cache (or change the prompt, which changes the cache key) to ask the model again.
"""

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from driftpilot.config import LLMConfig  # noqa: E402
from driftpilot.envfile import load_env_file  # noqa: E402
from driftpilot.evaluation.dataset import load_cases  # noqa: E402
from driftpilot.evaluation.report import per_case_markdown, summary_markdown  # noqa: E402
from driftpilot.evaluation.runner import (  # noqa: E402
    SETUPS,
    CachingLLM,
    SetupResult,
    prompt_stability,
    run_setup,
)
from driftpilot.triage.llm import build_llm  # noqa: E402

LOCAL_SKIP = (
    "skipped by choice: local model not installed (8 GB laptop); OllamaClient exists — "
    "set llm.provider: ollama to run it"
)


def phase3_analytics_check() -> list[str]:
    """Re-run the Phase 3 gate on simulated history: are the planted patterns found?"""
    spec = importlib.util.spec_from_file_location("sim", ROOT / "scripts" / "simulate_history.py")
    sim = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sim)
    from datetime import timedelta

    from driftpilot.history.analytics import analyze, episodes_frame
    from driftpilot.history.verdict_monitor import monitor

    events, runs = sim.simulate(seed=7)
    report = analyze(events, runs)
    spike = (report.period_start + timedelta(days=sim.SPIKE_DAY)).date()
    top_day = max(report.day_anomalies, key=lambda a: a.z).day if report.day_anomalies else None
    top_rec = max(report.recurring, key=lambda r: r.episodes, default=None)
    mon = monitor(episodes_frame(events, runs), report.period_end)
    yes = lambda ok: "✅ found" if ok else "❌ missed"  # noqa: E731
    return [
        "## Analytics on simulated history (planted patterns)",
        "",
        "| Planted | Result |",
        "| --- | --- |",
        f"| Drift spike on {spike} | {yes(top_day == spike)} as top unusual day; "
        f"{yes(spike in report.change_points)} as change-point |",
        f"| `{sim.RECURRING[0]}` `{sim.RECURRING[1]}` recurring | "
        f"{yes(top_rec is not None and (top_rec.address, top_rec.attribute) == sim.RECURRING)} |",
        f"| Human overrule rise | {yes(mon.breached)} "
        f"({mon.baseline_overrule_rate:.0%} → {mon.recent_overrule_rate:.0%}) |",
    ]


LIVE = [
    "## Measured in live runs (demo environments)",
    "",
    "| Metric | Result | Where |",
    "| --- | --- | --- |",
    '| Codify verification (GitHub, scenario 5) | verified on attempt 1, plan proof "No changes" | '
    "PR driftpilot-demo/infra#1 |",
    "| Codify verification (Docker, memory) | verified on attempt 1 with Flash-Lite "
    "(3.5 Flash: attempt 3) | local runs, Phase 2 |",
    "| Import verification (Docker container) | correctly **rejected**: provider forces "
    "replacement (`env`) | local run, Phase 2 |",
    "| Time to detect, event-driven (relay) | 10–18 s from the change to the run starting | "
    "infra runs, Phases 1–2 |",
    "| Time to detect, scheduled | ≤ 6 h (cron `17 */6 * * *`) | infra workflow |",
    "| Cost per run | free tier (Gemini Flash-Lite); calls and tokens per setup are above | |",
]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--cases", type=Path, default=ROOT / "eval" / "cases")
    parser.add_argument("--out", type=Path, default=ROOT / "eval" / "results")
    parser.add_argument("--cache", type=Path, default=ROOT / "eval" / "cache")
    parser.add_argument("--no-llm", action="store_true", help="skip setups that need an LLM")
    parser.add_argument(
        "--stability", type=int, default=5, help="repeats for prompt stability (0 = off)"
    )
    args = parser.parse_args(argv)

    load_env_file(ROOT / ".env")
    cases = load_cases(args.cases)
    fixtures = ROOT / "tests" / "fixtures"
    inner = None if args.no_llm else build_llm(LLMConfig())
    if inner is None and not args.no_llm:
        print("No LLM key found (GEMINI_API_KEY): LLM setups will be skipped.", file=sys.stderr)

    results: list[SetupResult] = []
    for setup in SETUPS:
        print(f"running: {setup.name} ...", file=sys.stderr)
        if setup.llm == "local":
            results.append(SetupResult(setup, skipped=LOCAL_SKIP))
            continue
        llm = CachingLLM(inner, args.cache) if inner and setup.llm == "cloud" else None
        results.append(run_setup(cases, setup, llm, ROOT, fixtures))

    stability = None
    if inner is not None and args.stability > 1:
        print(f"prompt stability: {args.stability} repeats ...", file=sys.stderr)
        stability = prompt_stability(
            cases,
            lambda salt: CachingLLM(inner, args.cache, salt),
            ROOT,
            fixtures,
            repeats=args.stability,
        )

    extras = [*phase3_analytics_check(), "", *LIVE]
    args.out.mkdir(parents=True, exist_ok=True)
    model = inner.model if inner else None
    (args.out / "summary.md").write_text(summary_markdown(cases, results, stability, extras, model))
    (args.out / "per_case.md").write_text(per_case_markdown(results))
    (args.out / "results.json").write_text(
        json.dumps(
            {
                "model": model,
                "setups": [
                    {
                        "setup": r.setup.name,
                        "skipped": r.skipped,
                        "metrics": None if r.skipped else r.metrics(),
                        "llm_calls": r.llm_calls + r.cache_hits,
                        "items": [i.model_dump() for i in r.items],
                    }
                    for r in results
                ],
                "stability": stability,
            },
            indent=2,
        )
    )
    print((args.out / "summary.md").read_text())


if __name__ == "__main__":
    main()
