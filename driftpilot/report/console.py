"""Terminal output for `driftpilot scan` and `driftpilot report` (rich tables)."""

from typing import TYPE_CHECKING

from rich.console import Console
from rich.table import Table

from driftpilot.models import ScanResult
from driftpilot.report import change_text, counts, decided_by, severity_of, sorted_findings

if TYPE_CHECKING:
    from driftpilot.history.analytics import AnalyticsReport
    from driftpilot.history.verdict_monitor import MonitorReport

_STYLE = {
    "critical": "bold red",
    "high": "red",
    "medium": "yellow",
    "low": "blue",
    "triage": "white",
    "none": "dim",
}


def print_result(result: ScanResult, console: Console, show_noise: bool = False) -> None:
    findings = sorted_findings(result, show_noise)
    c = counts(result)
    if findings:
        table = Table(title="Drift", title_justify="left")
        for column in ("Severity", "Resource", "Setting", "Change", "Action", "Why"):
            table.add_column(column, overflow="fold")
        for f in findings:
            v = result.verdicts.get(f.id)
            sev = severity_of(v)
            label = "needs triage" if sev == "triage" else sev
            table.add_row(
                f"[{_STYLE[sev]}]{label}[/]",
                f.address,
                f.attribute_path or "—",
                change_text(f),
                v.recommended_action if v else "—",
                f"{v.reason} [dim]({decided_by(v)})[/]" if v else f"[dim]{decided_by(v)}[/]",
            )
        console.print(table)

    if result.unmanaged:
        table = Table(title="Unmanaged resources (not in Terraform state)", title_justify="left")
        for column in ("Kind", "Name", "ID", "Created"):
            table.add_column(column)
        for u in result.unmanaged:
            created = f"{u.created_at:%Y-%m-%d %H:%M}" if u.created_at else "—"
            table.add_row(u.resource_kind, u.name, u.resource_id[:12], created)
        console.print(table)

    if not findings and not result.unmanaged:
        console.print("[green]No drift detected.[/]")
    if c["noise"] and not show_noise:
        console.print(f"[dim]{c['noise']} noise finding(s) hidden (use --show-noise).[/]")
    for error in result.errors:
        console.print(f"[red]error:[/] {error}")


def print_history(report: "AnalyticsReport", monitor: "MonitorReport", console: Console) -> None:
    """Terminal summary for `driftpilot report`."""
    h = report.health
    if report.period_start is None:
        console.print("[dim]No history yet.[/]")
        return
    console.print(
        f"[bold]{report.period_start:%Y-%m-%d} → {report.period_end:%Y-%m-%d}[/] · "
        f"{h.runs} runs · {report.episodes} drift episodes · "
        f"{h.pct_runs_zero_drift}% runs clean · "
        f"mean time to fix {h.mean_hours_to_remediate or '—'} h · "
        f"{h.pct_resources_ever_drifted or '—'}% resources ever drifted"
    )
    sections = [
        (
            "Recurring drift (3+ times in 14 days)",
            ("Resource", "Setting", "Episodes"),
            [
                (r.address, r.attribute or "—", str(r.episodes))
                for r in sorted(report.recurring, key=lambda r: -r.episodes)
            ],
        ),
        (
            "Unusual days (z-score)",
            ("Day", "New", "Usual", "z"),
            [
                (str(a.day), str(a.new_episodes), str(a.baseline_mean), str(a.z))
                for a in sorted(report.day_anomalies, key=lambda a: -a.z)
            ],
        ),
        (
            "Unusual runs (Isolation Forest)",
            ("Run", "Time", "Findings"),
            [
                (a.run_id, f"{a.timestamp:%Y-%m-%d %H:%M}", str(a.finding_count))
                for a in report.run_anomalies
            ],
        ),
        (
            "Mix shifts (last 14 days vs previous 56)",
            ("Dimension", "PSI", "χ² p", "Shifted"),
            [
                (s.dimension, str(s.psi), str(s.chi2_p), "yes" if s.shifted else "no")
                for s in report.shifts
            ],
        ),
    ]
    for title, columns, rows in sections:
        table = Table(title=title, title_justify="left")
        for column in columns:
            table.add_column(column)
        for row in rows:
            table.add_row(*row)
        if not rows:
            table.add_row(*(["none"] + [""] * (len(columns) - 1)))
        console.print(table)
    if report.change_points:
        console.print("Change-points: " + ", ".join(str(d) for d in report.change_points))
    if monitor.alerts:
        console.print("[bold red]Verdict monitor:[/]")
        for alert in monitor.alerts:
            console.print(f"  • {alert}")
    else:
        console.print("[green]Verdict monitor: no alerts.[/]")
