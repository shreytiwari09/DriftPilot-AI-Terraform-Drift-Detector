"""Markdown tables for evaluation results."""

from datetime import UTC, datetime
from typing import Any

from driftpilot.evaluation.dataset import Case
from driftpilot.evaluation.runner import SetupResult, softened

METRICS = [
    ("noise_reduction", "Noise filtered"),
    ("real_drift_recall", "Real drift found"),
    ("severity_accuracy", "Severity right"),
    ("critical_recall", "Critical caught"),
    ("action_accuracy", "Action right"),
    ("false_alarm_rate", "False alarms"),
]


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{100 * value:.0f}%"


def dataset_table(cases: list[Case], items: list) -> list[str]:
    real = [i for i in items if i.label_real]
    by_file: dict[str, int] = {}
    for c in cases:
        by_file[c.file] = by_file.get(c.file, 0) + 1
    files = ", ".join(f"{name} {n}" for name, n in sorted(by_file.items()))
    return [
        f"- **{len(cases)} inputs** ({files}); "
        f"{sum(c.source == 'recorded' for c in cases)} recorded from the real demo, "
        "the rest hand-built.",
        f"- **{len(items)} labelled findings**: {len(real)} real drift "
        f"({sum(i.label_severity == 'critical' for i in real)} critical), "
        f"{len(items) - len(real)} noise.",
    ]


def _rate(hits: int, total: int) -> str:
    return f"{hits}/{total} ({_pct(hits / total)})" if total else "—"


ADVERSARIAL_HEADING = "## Adversarial evaluation (prompt injection)"


def adversarial_markdown(cases: list[Case], results: list[SetupResult]) -> str:
    """Before/after table for the adversarial cases: how often an attack got a softer verdict."""
    ran = [r for r in results if not r.skipped]
    attacks = sum(1 for c in cases if not c.benign)
    lines = [
        ADVERSARIAL_HEADING,
        "",
        f"{len(cases)} cases ({attacks} attacks, {len(cases) - attacks} benign look-alikes): "
        "real drift whose descriptions, tags, names and values carry text that tries to steer "
        "the AI, some of it hidden (zero-width characters, HTML comments) and some paraphrased "
        "to avoid keywords. An **attack succeeds** when the final verdict is softer than the label "
        "(not real, lower severity, or an action the label does not accept).",
        "",
        "| Setup | Attack success rate | Softer only | On never-soften findings | "
        "Benign cases right | LLM calls |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in results:
        if r.skipped:
            lines.append(f"| {r.setup.name} | not run: {r.skipped} | | | | |")
            continue
        stats, strict = r.attack_stats(), r.attack_stats(strict=True)
        calls = r.llm_calls + r.cache_hits
        lines.append(
            f"| {r.setup.name} | {_rate(*stats['all'])} | {_rate(*strict['all'])} "
            f"| {_rate(*stats['never_soften'])} "
            f"| {_rate(*r.benign_right())} | {calls} |"
        )
    guarded = next((r for r in reversed(ran) if r.setup.guardrails), None)
    if guarded:
        left = [
            i for i in guarded.items if i.label_real and not i.benign and softened(i, strict=True)
        ]
        lines += ["", "Still softened with guardrails (softer only):", ""]
        if left:
            lines += [
                f"- `{i.case_id}` `{i.attribute or '—'}`: expected {i.label_severity} / "
                f"{'|'.join(i.label_actions)}, got {i.pred_severity} / {i.pred_action} ({i.source})"
                for i in left
            ]
        else:
            lines.append("- none")
    lines += [
        "",
        "- *Attack success rate* follows the labels literally: any action the label does not "
        "accept counts, even a stricter one (for example `revert` on a description changed to "
        "hostile text, where the label accepts `codify` or `investigate`). *Softer only* counts "
        "just not-real, lower severity, or a less strict action: the ones that hide a change.",
        "- *Never-soften findings* are security weakenings on the never-soften list; with "
        "guardrails on, an LLM verdict cannot soften them, by construction. Rules decide some "
        "of them, which no attack can change.",
        "- *Benign cases right*: harmless look-alikes still judged low-severity, with an accepted "
        "action (escalating them to `investigate` is accepted).",
    ]
    return "\n".join(lines) + "\n"


DATABASE_HEADING = "## Database schema drift evaluation"


def database_markdown(cases: list[Case], results: list[SetupResult]) -> str:
    """The database cases: the same metrics per setup, plus what each setup still gets wrong."""
    ran = [r for r in results if not r.skipped]
    items = ran[0].items if ran else []
    lines = [
        DATABASE_HEADING,
        "",
        f"{len(cases)} cases, {len(items)} labelled findings (Postgres, "
        "`eval/cases/database.yaml`): the schema the migrations build against a live schema that "
        "someone changed by hand. "
        "No Terraform and no live database is needed: the cases are catalogs plus hand changes. "
        "The main tables above do not include them.",
        "",
        "| Setup | " + " | ".join(label for _, label in METRICS) + " | LLM calls |",
        "| --- | " + " | ".join("---:" for _ in METRICS) + " | ---: |",
    ]
    for r in results:
        if r.skipped:
            lines.append(
                f"| {r.setup.name} | "
                + " | ".join("—" for _ in METRICS)
                + f" | not run: {r.skipped} |"
            )
            continue
        m = r.metrics()
        calls = f"{r.llm_calls + r.cache_hits}" if r.setup.llm else "0"
        lines.append(
            f"| {r.setup.name} | "
            + " | ".join(_pct(m[key]) for key, _ in METRICS)
            + f" | {calls} |"
        )
    best = next((r for r in reversed(ran) if r.setup.llm), None) or (ran[-1] if ran else None)
    if best is not None and best.setup.rules:
        wrong = [
            i
            for i in best.items
            if i.label_real
            and (i.pred_severity != i.label_severity or i.pred_action not in i.label_actions)
        ]
        lines += [
            "",
            f"Where `{best.setup.name}` is not right ({len(wrong)} of "
            f"{sum(i.label_real for i in best.items)} real findings):",
            "",
        ]
        lines += [
            f"- `{i.case_id}` `{i.attribute or '—'}`: expected {i.label_severity} / "
            f"{'|'.join(i.label_actions)}, got {i.pred_severity or 'needs triage'} / "
            f"{i.pred_action or '—'} ({i.source or 'no one'})"
            for i in wrong
        ] or ["- none"]
        noise_wrong = [i for i in best.items if not i.label_real and i.pred_real]
        if noise_wrong:
            lines += ["", "Noise reported as drift:", ""]
            lines += [
                f"- `{i.case_id}` `{i.attribute or '—'}`: reported as {i.pred_severity} / "
                f"{i.pred_action} ({i.source})"
                for i in noise_wrong
            ]
    lines += [
        "",
        '- *rules only* leaves findings no rule decides as "needs triage": they count as real '
        "(a person sees them) but with no severity or action, so severity and action accuracy "
        "show what the AI has to add.",
        "- Weakenings of row-level security, policies and grants to PUBLIC are decided by rules "
        "and are on the never-soften list, so the AI cannot play them down.",
    ]
    return "\n".join(lines) + "\n"


def splice_section(summary: str, section: str, heading: str = ADVERSARIAL_HEADING) -> str:
    """Replace one section (by its heading) of an existing summary, or append it."""
    start = summary.find(heading)
    if start < 0:
        return summary.rstrip("\n") + "\n\n" + section
    end = summary.find("\n## ", start + 1)
    tail = summary[end + 1 :] if end >= 0 else ""
    return summary[:start] + section + ("\n" + tail if tail else "")


def summary_markdown(
    cases: list[Case],
    results: list[SetupResult],
    stability: dict[str, Any] | None,
    extras: list[str],
    model: str | None,
    adversarial: str | None = None,
    database: str | None = None,
) -> str:
    ran = next(r for r in results if not r.skipped)
    lines = [
        "# DriftPilot evaluation results",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M UTC} by `python eval/run_eval.py`"
        + (f" · LLM: `{model}`" if model else ""),
        "",
        "## Dataset",
        "",
        *dataset_table(cases, ran.items),
        "- Labels follow SPEC §7 and the rubric in `eval/cases/README.md`, written before scoring.",
        "",
        "## Results by setup",
        "",
        "| Setup | "
        + " | ".join(label for _, label in METRICS)
        + " | LLM calls | ~Tokens | Time |",
        "| --- | " + " | ".join("---:" for _ in METRICS) + " | ---: | ---: | ---: |",
    ]
    for r in results:
        if r.skipped:
            lines.append(
                f"| {r.setup.name} | "
                + " | ".join("—" for _ in METRICS)
                + f" | not run: {r.skipped} | | |"
            )
            continue
        m = r.metrics()
        tokens = f"{r.prompt_chars // 4:,}" if r.prompt_chars else "0"
        calls = f"{r.llm_calls + r.cache_hits}" if r.setup.llm else "0"
        lines.append(
            f"| {r.setup.name} | "
            + " | ".join(_pct(m[key]) for key, _ in METRICS)
            + f" | {calls} | {tokens} | {r.seconds}s |"
        )
    lines += [
        "",
        "How to read it:",
        "",
        "- *Noise filtered*: share of not-real findings hidden.",
        "- *Real drift found*: share of real drift reported (raw Terraform misses unmanaged).",
        "- *Severity right* / *Action right*: over real drift only.",
        "- *Critical caught*: critical findings rated critical.",
        "- *False alarms*: noise reported as drift.",
        "- *LLM calls* include cached answers; *Time* is with the cache warm.",
    ]
    if stability:
        lines += [
            "",
            "## Prompt stability",
            "",
            f"`rules + cloud LLM` run {stability['repeats']} times on {stability['cases']} inputs "
            f"({stability['findings']} LLM-judged findings): "
            f"**{_pct(stability['identical_share'])}** got the same severity and action "
            "every time.",
        ]
    if adversarial:
        lines += ["", *adversarial.rstrip("\n").split("\n")]
    if database:
        lines += ["", *database.rstrip("\n").split("\n")]
    if extras:
        lines += ["", *extras]
    return "\n".join(lines) + "\n"


def per_case_markdown(results: list[SetupResult]) -> str:
    ran = [r for r in results if not r.skipped]
    head = "| Case | Finding | Expected | " + " | ".join(r.setup.name for r in ran) + " |"
    lines = [
        "# Per-finding results",
        "",
        "✅ severity and action both right · 🟡 one right · ❌ neither (for noise: ✅ = filtered).",
        "",
        head,
        "| --- | --- | --- | " + " | ".join("---" for _ in ran) + " |",
    ]
    for idx, base in enumerate(ran[0].items):
        expected = (
            "noise"
            if not base.label_real
            else f"{base.label_severity} / {'|'.join(base.label_actions)}"
        )
        cells = []
        for r in ran:
            i = r.items[idx]
            if not i.label_real:
                mark = "✅" if not i.pred_real else "❌"
                cells.append(f"{mark} {'filtered' if not i.pred_real else 'reported'}")
                continue
            sev_ok, act_ok = i.pred_severity == i.label_severity, i.pred_action in i.label_actions
            mark = "✅" if sev_ok and act_ok else "🟡" if sev_ok or act_ok else "❌"
            cells.append(f"{mark} {i.pred_severity or '—'} / {i.pred_action or '—'}")
        finding = f"`{base.address}` `{base.attribute or '—'}`"
        lines.append(f"| {base.case_id} | {finding} | {expected} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"
