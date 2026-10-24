"""Command-line interface: `driftpilot scan | action | version`."""

import os
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from driftpilot import __version__
from driftpilot.collector import TerraformError
from driftpilot.config import load_config
from driftpilot.models import ScanResult
from driftpilot.report import counts
from driftpilot.report.console import print_result
from driftpilot.report.summary import build_summary
from driftpilot.scan import run_scan

app = typer.Typer(help="Detect, triage and fix Terraform drift.", no_args_is_help=True)
console = Console()
err_console = Console(stderr=True)


def _scan_or_exit(
    working_dir: Path, config_path: Path | None, plan_json: Path | None, state_json: Path | None
) -> ScanResult:
    try:
        config = load_config(config_path, working_dir)
        return run_scan(working_dir, config, plan_json=plan_json, state_json=state_json)
    except (TerraformError, OSError, ValueError) as e:
        err_console.print(f"[red]error:[/] {e}")
        raise typer.Exit(1) from e


@app.command()
def scan(
    directory: Annotated[Path, typer.Option("--dir", help="Terraform working directory.")] = Path(
        "."
    ),
    config: Annotated[
        Path | None, typer.Option(help="Config file (default: <dir>/.driftpilot.yml).")
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
    show_noise: Annotated[
        bool, typer.Option(help="Also list findings rules marked as noise.")
    ] = False,
    plan_json: Annotated[
        Path | None, typer.Option(help="Replay a recorded `terraform show -json` plan.")
    ] = None,
    state_json: Annotated[
        Path | None, typer.Option(help="Replay a recorded state (for scanners) with --plan-json.")
    ] = None,
    fail_on_drift: Annotated[
        bool, typer.Option(help="Exit with code 2 if real drift or unmanaged resources are found.")
    ] = False,
) -> None:
    """Check a Terraform directory for drift and unmanaged resources."""
    result = _scan_or_exit(directory, config, plan_json, state_json)
    if json_output:
        print(result.model_dump_json(indent=2))
    else:
        print_result(result, console, show_noise)
    if fail_on_drift and (result.real_findings or result.unmanaged):
        raise typer.Exit(2)


@app.command()
def action(
    working_directory: Annotated[
        Path, typer.Option(envvar="DRIFTPILOT_WORKING_DIRECTORY", help="Terraform folder.")
    ] = Path("."),
    config_path: Annotated[
        Path, typer.Option(envvar="DRIFTPILOT_CONFIG_PATH", help="Repo config file.")
    ] = Path(".driftpilot.yml"),
) -> None:
    """Entry point for the GitHub Action: scan, then write the job summary and outputs."""
    result = _scan_or_exit(
        working_directory, config_path if config_path.exists() else None, None, None
    )
    print_result(result, console)

    summary = build_summary(result)
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(path, "a") as f:
            f.write(summary)
    else:
        print(summary)

    c = counts(result)
    if path := os.environ.get("GITHUB_OUTPUT"):
        with open(path, "a") as f:
            f.write(
                f"drift-found={'true' if result.real_findings or result.unmanaged else 'false'}\n"
            )
            f.write(f"critical-count={c['critical']}\n")
            f.write(f"finding-count={len(result.real_findings)}\n")
            f.write(f"unmanaged-count={c['unmanaged']}\n")
    if c["critical"]:  # annotation shown at the top of the workflow run page
        print(f"::error title=DriftPilot::{c['critical']} critical drift finding(s)")


@app.command()
def version() -> None:
    """Show the DriftPilot version."""
    print(__version__)
