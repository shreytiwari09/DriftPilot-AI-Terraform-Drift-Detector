"""Markdown report for the GitHub Actions job summary (SPEC §4.7)."""

from driftpilot.models import ScanResult
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
            "| Severity | Resource | Setting | Change | Action | Why |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for f in real:
            v = result.verdicts.get(f.id)
            why = f"{v.reason} _({decided_by(v)})_" if v else decided_by(v)
            action = f"`{v.recommended_action}`" if v else "—"
            lines.append(
                f"| {_BADGE[v.severity if v else 'triage']} | `{_cell(f.address)}` "
                f"| `{_cell(f.attribute_path or '—')}` | {_cell(change_text(f))} | {action} "
                f"| {_cell(why)} |"
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

    if result.remediations:
        lines += ["", "### Fixes", "", "| Action | Opened | Verified |", "| --- | --- | --- |"]
        for r in result.remediations:
            link = r.pr_url or r.issue_url or "—"
            kind = "pull request" if r.pr_url else "issue"
            verified = "✅ zero-change plan" if r.verified else "—"
            lines.append(f"| `{r.action}` | [{kind}]({link}) | {verified} |")

    if result.errors:
        lines += ["", "### Errors", ""] + [f"- {_cell(e)}" for e in result.errors]
    return "\n".join(lines) + "\n"
