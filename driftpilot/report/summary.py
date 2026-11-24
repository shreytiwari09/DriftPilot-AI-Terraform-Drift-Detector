"""Markdown report for the GitHub Actions job summary (SPEC §4.7)."""

from driftpilot.models import DriftFinding, ScanResult
from driftpilot.report import change_text, counts, decided_by, sorted_findings

_BADGE = {
    "critical": "🔴 critical",
    "high": "🟠 high",
    "medium": "🟡 medium",
    "low": "🔵 low",
    "triage": "⚪ needs triage",
    "none": "noise",
}


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _changed_by_section(findings: list[DriftFinding]) -> list[str]:
    """Who changed what, for findings a cloud audit event was matched to."""
    rows = []
    for f in findings:
        c = f.change_context
        if c is None:
            continue
        who = f"`{_cell(c.actor)}`" if c.actor else "unknown"
        rows.append(
            f"| `{_cell(f.address)}` | {who} | `{_cell(c.event_name)}` "
            f"| {_cell(c.event_source or '—')} | {_cell(c.event_time or '—')} |"
        )
    if not rows:
        return []
    header = ["| Resource | Changed by | Call | Source | Time |", "| --- | --- | --- | --- | --- |"]
    seen = list(dict.fromkeys(rows))
    return ["", "### Who changed it", "", "Matched from a cloud audit event by name or ID.", "",
            *header, *seen]  # fmt: skip


def _guardrails_section(result: ScanResult) -> list[str]:
    """What the guardrails did this run; empty when the LLM was not used and nothing fired."""
    if not (result.audit or result.guardrail_events):
        return []
    by_kind: dict[str, list] = {}
    for e in result.guardrail_events:
        by_kind.setdefault(e.kind, []).append(e)
    budget = f" of {result.llm_call_limit}" if result.llm_call_limit is not None else ""
    overrides = by_kind.get("never-soften", [])
    suspicious = by_kind.get("suspicious-input", [])
    lines = [
        "",
        "### Guardrails",
        "",
        f"- LLM calls: {len(result.audit)}{budget}",
        f"- Never-soften overrides: {len(overrides)}"
        + "".join(f"\n  - {_cell(e.detail)}" for e in overrides),
        f"- Suspicious inputs: {len(suspicious)}"
        + "".join(f"\n  - {_cell(e.detail)}" for e in suspicious),
    ]
    if sanitized := by_kind.get("sanitized"):
        lines.append(f"- Inputs cleaned before the AI saw them: {len(sanitized)}")
    for kind, text in (
        ("budget-exceeded", "LLM budget exceeded"),
        ("pr-limit", "PR limit reached, opened as an issue instead"),
        ("patch-too-large", "Patch too large, sent as an unverified issue"),
    ):
        lines += [f"- ⚠️ {text}: {_cell(e.detail)}" for e in by_kind.get(kind, [])]
    return lines


def build_summary(result: ScanResult, heading: str = "## DriftPilot drift report") -> str:
    c = counts(result)
    lines = [
        heading,
        "",
        f"Run `{result.run_id}` · directory `{result.working_dir}` · "
        f"{result.started_at:%Y-%m-%d %H:%M UTC}",
        "",
    ]
    real = sorted_findings(result)
    if not real and not result.unmanaged:
        lines.append("✅ **No drift detected.**")
    else:
        lines += [
            "| 🔴 Critical | 🟠 High | 🟡 Medium | 🔵 Low | ⚪ Needs triage | Unmanaged |",
            "| ---: | ---: | ---: | ---: | ---: | ---: |",
            f"| {c['critical']} | {c['high']} | {c['medium']} | {c['low']} | {c['triage']} "
            f"| {c['unmanaged']} |",
        ]
    if c["noise"]:
        lines += ["", f"_{c['noise']} noise finding(s) filtered by rules._"]

    if real:
        tagged = any((v := result.verdicts.get(f.id)) and v.controls for f in real)
        lines += [
            "",
            "### Drift",
            "",
            "| Severity | Resource | Setting | Change | Action |"
            + (" Compliance tags |" if tagged else "")
            + " Why |",
            "| --- | --- | --- | --- | --- |" + (" --- |" if tagged else "") + " --- |",
        ]
        for f in real:
            v = result.verdicts.get(f.id)
            why = f"{v.reason} _({decided_by(v)})_" if v else decided_by(v)
            action = f"`{v.recommended_action}`" if v else "—"
            tags = f" {', '.join(f'`{c}`' for c in v.controls) if v and v.controls else '—'} |"
            lines.append(
                f"| {_BADGE[v.severity if v else 'triage']} | `{_cell(f.address)}` "
                f"| `{_cell(f.attribute_path or '—')}` | {_cell(change_text(f))} | {action} |"
                f"{tags if tagged else ''} {_cell(why)} |"
            )
        lines += _changed_by_section(real)

    if result.unmanaged:
        lines += [
            "",
            "### Unmanaged resources",
            "",
            "Exist on the platform but not in Terraform state. Usual fix: `import` into Terraform.",
            "",
            "| Kind | Name | ID | Created |",
            "| --- | --- | --- | --- |",
        ]
        for u in result.unmanaged:
            created = f"{u.created_at:%Y-%m-%d %H:%M}" if u.created_at else "—"
            name, rid = _cell(u.name), _cell(u.resource_id[:20])
            lines.append(f"| {u.resource_kind} | `{name}` | `{rid}` | {created} |")

    if result.remediations:
        lines += ["", "### Fixes", "", "| Action | Opened | Verified |", "| --- | --- | --- |"]
        for r in result.remediations:
            link = r.pr_url or r.issue_url or "—"
            kind = "pull request" if r.pr_url else "issue"
            verified = "✅ zero-change plan" if r.verified else "—"
            lines.append(f"| `{r.action}` | [{kind}]({link}) | {verified} |")

    lines += _guardrails_section(result)

    if result.errors:
        lines += ["", "### Errors", ""] + [f"- {_cell(e)}" for e in result.errors]
    return "\n".join(lines) + "\n"


def build_combined_summary(sections: list[tuple[str, ScanResult]]) -> str:
    """One report with a section per check, e.g. infrastructure and database.

    A single section keeps the usual heading; several share one title.
    """
    if len(sections) == 1:
        result = sections[0][1]
        if result.context.drift_type == "database":
            return build_summary(result, "## DriftPilot database drift report")
        return build_summary(result)
    parts = ["# DriftPilot drift report\n"]
    parts += [build_summary(result, f"## {title}") for title, result in sections]
    return "\n".join(parts)
