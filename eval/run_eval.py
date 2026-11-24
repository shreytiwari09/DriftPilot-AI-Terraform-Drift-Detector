"""Run the DriftPilot evaluation; write markdown tables to eval/results/ (SPEC §8).

    python eval/run_eval.py                 # all setups (cloud LLM: GEMINI_API_KEY, e.g. .env)
    python eval/run_eval.py --no-llm        # only the setups that need no LLM
    python eval/run_eval.py --stability 0   # skip the prompt-stability repeats
    python eval/run_eval.py --adversarial-only --max-calls 80   # only the prompt-injection cases
    python eval/run_eval.py --database-only --max-calls 40      # only the database schema cases

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
from driftpilot.evaluation.dataset import (  # noqa: E402
    load_adversarial,
    load_cases,
    load_database,
)
from driftpilot.evaluation.report import (  # noqa: E402
    DATABASE_HEADING,
    adversarial_markdown,
    database_markdown,
    per_case_markdown,
    splice_section,
    summary_markdown,
)
from driftpilot.evaluation.runner import (  # noqa: E402
    ADVERSARIAL_SETUPS,
    DATABASE_SETUPS,
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


STABILITY_NOTE = (
    "## Prompt stability\n\n"
    "Not re-run for the current prompt (`triage-v4`) to save LLM quota. The last measurement, "
    "on the earlier prompt `triage-v2` (5 repeats, 12 inputs, 12 LLM-judged findings), gave "
    "100% identical severity and action."
)

AWS_BEFORE = (
    "Before the AWS rules (rule pack at the start of version 2 phase 7, original 25 AWS cases, "
    "rules only, measured then): severity right 16%, critical caught 36%, action right 16%."
)


def aws_rules_section(results: list[SetupResult]) -> list[str]:
    """Rules-only (and rules + AI) scores on the AWS cases alone; no extra LLM calls."""
    rows = []
    for r in results:
        if r.skipped or r.setup.name not in ("rules only", "rules + cloud LLM"):
            continue
        aws = SetupResult(r.setup, items=[i for i in r.items if i.case_id.startswith("aws-")])
        m = aws.metrics()
        rows.append(
            f"| {r.setup.name} | {m['severity_accuracy']:.0%} | {m['critical_recall']:.0%} | "
            f"{m['action_accuracy']:.0%} | {m['noise_reduction']:.0%} |"
        )
    return [
        "## AWS cases only",
        "",
        "The `aws-*` cases (31 inputs) scored on their own, with the current rules.",
        "",
        "| Setup | Severity right | Critical caught | Action right | Noise filtered |",
        "| --- | ---: | ---: | ---: | ---: |",
        *rows,
        "",
        AWS_BEFORE,
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


def _setup_json(r: SetupResult) -> dict:
    return {
        "setup": r.setup.name,
        "skipped": r.skipped,
        "metrics": None if r.skipped else r.metrics(),
        "attack_stats": None if r.skipped else r.attack_stats(),
        "llm_calls": r.llm_calls + r.cache_hits,
        "items": [i.model_dump() for i in r.items],
    }


def run_adversarial(cases, inner, cache: Path, budget: int | None, root: Path, fixtures: Path):
    """The adversarial setups over the adversarial cases; stops at the first LLM error."""
    results: list[SetupResult] = []
    left = budget
    for setup in ADVERSARIAL_SETUPS:
        print(f"running (adversarial): {setup.name} ...", file=sys.stderr)
        llm = CachingLLM(inner, cache, max_calls=left) if inner else None
        result = run_setup(cases, setup, llm, root, fixtures)
        if llm is not None and llm.errors:
            result = SetupResult(setup, skipped=f"stopped, {llm.errors[0]} (no results kept)")
        if left is not None and llm is not None:
            left -= llm.calls
        results.append(result)
    return results


def run_database(cases, inner, cache: Path, budget: int | None, root: Path, fixtures: Path):
    """The database setups over the database cases; stops at the first LLM error."""
    results: list[SetupResult] = []
    left = budget
    for setup in DATABASE_SETUPS:
        print(f"running (database): {setup.name} ...", file=sys.stderr)
        llm = CachingLLM(inner, cache, max_calls=left) if inner and setup.llm else None
        result = run_setup(cases, setup, llm, root, fixtures)
        if llm is not None and llm.errors:
            result = SetupResult(setup, skipped=f"stopped, {llm.errors[0]} (no results kept)")
        if left is not None and llm is not None:
            left -= llm.calls
        results.append(result)
    return results


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
    parser.add_argument(
        "--adversarial-only",
        action="store_true",
        help="only the prompt-injection cases; updates that section of summary.md",
    )
    parser.add_argument(
        "--database-only",
        action="store_true",
        help="only the database schema cases; updates that section of summary.md",
    )
    parser.add_argument("--skip-adversarial", action="store_true", help="skip the injection cases")
    parser.add_argument("--skip-database", action="store_true", help="skip the database cases")
    parser.add_argument(
        "--max-calls",
        type=int,
        default=None,
        help="cap on new (uncached) LLM calls for the adversarial or database cases",
    )
    args = parser.parse_args(argv)

    load_env_file(ROOT / ".env")
    cases = load_cases(args.cases)
    adversarial_cases = load_adversarial(args.cases)
    database_cases = load_database(args.cases)
    fixtures = ROOT / "tests" / "fixtures"
    inner = None if args.no_llm else build_llm(LLMConfig())
    if inner is None and not args.no_llm:
        print("No LLM key found (GEMINI_API_KEY): LLM setups will be skipped.", file=sys.stderr)

    if args.database_only:
        results = run_database(database_cases, inner, args.cache, args.max_calls, ROOT, fixtures)
        section = database_markdown(database_cases, results)
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "database.md").write_text(section)
        summary = args.out / "summary.md"
        old = summary.read_text() if summary.exists() else "# DriftPilot evaluation results\n"
        summary.write_text(splice_section(old, section, DATABASE_HEADING))
        (args.out / "database.json").write_text(
            json.dumps([_setup_json(r) for r in results], indent=2)
        )
        print(section)
        return

    if args.adversarial_only:
        results = run_adversarial(
            adversarial_cases, inner, args.cache, args.max_calls, ROOT, fixtures
        )
        section = adversarial_markdown(adversarial_cases, results)
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "adversarial.md").write_text(section)
        summary = args.out / "summary.md"
        old = summary.read_text() if summary.exists() else "# DriftPilot evaluation results\n"
        summary.write_text(splice_section(old, section))
        (args.out / "adversarial.json").write_text(
            json.dumps([_setup_json(r) for r in results], indent=2)
        )
        print(section)
        return

    results: list[SetupResult] = []
    for setup in SETUPS:
        print(f"running: {setup.name} ...", file=sys.stderr)
        if setup.llm == "local":
            results.append(SetupResult(setup, skipped=LOCAL_SKIP))
            continue
        llm = CachingLLM(inner, args.cache) if inner and setup.llm == "cloud" else None
        result = run_setup(cases, setup, llm, ROOT, fixtures)
        if llm is not None and llm.errors:  # never publish numbers made of fallback verdicts
            result = SetupResult(setup, skipped=f"stopped, {llm.errors[0]} (no results kept)")
        results.append(result)

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

    adversarial = None
    adversarial_results: list[SetupResult] = []
    if adversarial_cases and not args.skip_adversarial:
        adversarial_results = run_adversarial(
            adversarial_cases, inner, args.cache, args.max_calls, ROOT, fixtures
        )
        adversarial = adversarial_markdown(adversarial_cases, adversarial_results)

    database = None
    database_results: list[SetupResult] = []
    if database_cases and not args.skip_database:
        database_results = run_database(
            database_cases, inner, args.cache, args.max_calls, ROOT, fixtures
        )
        database = database_markdown(database_cases, database_results)

    extras = [*aws_rules_section(results), "", *phase3_analytics_check(), "", *LIVE]
    if args.stability <= 1:
        extras = [STABILITY_NOTE, "", *extras]
    args.out.mkdir(parents=True, exist_ok=True)
    model = inner.model if inner else None
    (args.out / "summary.md").write_text(
        summary_markdown(cases, results, stability, extras, model, adversarial, database)
    )
    (args.out / "per_case.md").write_text(per_case_markdown(results))
    (args.out / "results.json").write_text(
        json.dumps(
            {
                "model": model,
                "setups": [_setup_json(r) for r in results],
                "adversarial": [_setup_json(r) for r in adversarial_results],
                "database": [_setup_json(r) for r in database_results],
                "stability": stability,
            },
            indent=2,
        )
    )
    print((args.out / "summary.md").read_text())


if __name__ == "__main__":
    main()
