"""Terminal output for `driftpilot scan` (rich tables)."""

from rich.console import Console
from rich.table import Table

from driftpilot.models import ScanResult
from driftpilot.report import change_text, counts, decided_by, severity_of, sorted_findings

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
