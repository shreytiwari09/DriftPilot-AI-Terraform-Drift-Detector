"""Markdown report for the GitHub Actions job summary (SPEC §4.7)."""

from driftpilot.models import ScanResult
from driftpilot.report import change_text, counts, sorted_findings

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


def build_summary(result: ScanResult) -> str:
    c = counts(result)
    lines = [
        "## DriftPilot drift report",
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
        lines += [
            "",
            "### Drift",
            "",
            "| Severity | Resource | Setting | Change | Why |",
            "| --- | --- | --- | --- | --- |",
        ]
        for f in real:
            v = result.verdicts.get(f.id)
            why = (
                f"{v.reason} (rule `{v.rule_id}`)"
                if v
                else "No rule decided; AI triage comes in v0.2."
            )
            lines.append(
                f"| {_BADGE[v.severity if v else 'triage']} | `{_cell(f.address)}` "
                f"| `{_cell(f.attribute_path or '—')}` | {_cell(change_text(f))} | {_cell(why)} |"
            )

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

    if result.errors:
        lines += ["", "### Errors", ""] + [f"- {_cell(e)}" for e in result.errors]
    return "\n".join(lines) + "\n"
