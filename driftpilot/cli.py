"""Command-line interface: `driftpilot scan | fix | action | version`."""

import os
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from driftpilot import __version__
from driftpilot.collector import TerraformError
from driftpilot.config import Config, load_config
from driftpilot.envfile import load_env_file
from driftpilot.models import ScanResult
from driftpilot.remediate.runner import ConsoleOutput, run_remediations
from driftpilot.report import counts
from driftpilot.report.console import print_result
from driftpilot.report.summary import build_summary
from driftpilot.scan import run_scan
from driftpilot.triage.llm import build_llm

app = typer.Typer(help="Detect, triage and fix Terraform drift.", no_args_is_help=True)
console = Console()
err_console = Console(stderr=True)

DirOption = Annotated[Path, typer.Option("--dir", help="Terraform working directory.")]
ConfigOption = Annotated[
    Path | None, typer.Option(help="Config file (default: <dir>/.driftpilot.yml).")
]
LLMOption = Annotated[bool, typer.Option("--llm/--no-llm", help="Use the LLM for triage.")]


@app.callback()
def _startup() -> None:
    """Detect, triage and fix Terraform drift."""
    load_env_file()  # local secrets such as GEMINI_API_KEY; real env vars win


def _load(working_dir: Path, config_path: Path | None) -> Config:
    try:
        return load_config(config_path, working_dir)
    except (OSError, ValueError) as e:
        err_console.print(f"[red]error:[/] {e}")
        raise typer.Exit(1) from e


def _scan_or_exit(
    working_dir: Path,
    config: Config,
    use_llm: bool,
    plan_json: Path | None = None,
    state_json: Path | None = None,
) -> ScanResult:
    llm = build_llm(config.llm) if use_llm else None
    if use_llm and llm is None and config.llm.enabled:
        err_console.print("[dim]No LLM API key found: undecided findings stay 'needs triage'.[/]")
    try:
        return run_scan(working_dir, config, plan_json=plan_json, state_json=state_json, llm=llm)
    except (TerraformError, OSError, ValueError) as e:
        err_console.print(f"[red]error:[/] {e}")
        raise typer.Exit(1) from e


@app.command()
def scan(
    directory: DirOption = Path("."),
    config: ConfigOption = None,
    use_llm: LLMOption = True,
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
    cfg = _load(directory, config)
    result = _scan_or_exit(directory, cfg, use_llm, plan_json, state_json)
    if json_output:
        print(result.model_dump_json(indent=2))
    else:
        print_result(result, console, show_noise)
    if fail_on_drift and (result.real_findings or result.unmanaged):
        raise typer.Exit(2)


@app.command()
def fix(
    directory: DirOption = Path("."),
    config: ConfigOption = None,
    finding: Annotated[
        str | None, typer.Option(help="Only the resource with this finding ID (see --json).")
    ] = None,
    write: Annotated[
        bool, typer.Option("--write/--dry-run", help="Write verified patches to the files.")
    ] = False,
) -> None:
    """Show the issues/PRs DriftPilot would open, with verified patches; never calls GitHub."""
    cfg = _load(directory, config).model_copy(update={"mode": "open-prs"})
    result = _scan_or_exit(directory, cfg, use_llm=True)
    if finding:
        keep = {finding}
        result.findings = [f for f in result.findings if f.id in keep]
        result.unmanaged = [u for u in result.unmanaged if u.id in keep]
        if not result.findings and not result.unmanaged:
            err_console.print(f"[red]error:[/] no real drift with finding ID {finding}")
            raise typer.Exit(1)
    output = ConsoleOutput(console, write_to=directory if write else None)
    outcomes = run_remediations(result, cfg, build_llm(cfg.llm), directory, output)
    if not outcomes:
        console.print("[green]Nothing to fix.[/]")
    for error in result.errors:
        console.print(f"[red]error:[/] {error}")


def _github_output(repo_name: str, token: str):
    from github import Auth, Github

    from driftpilot.remediate.github_out import GitHubOutput

    repo = Github(auth=Auth.Token(token)).get_repo(repo_name)
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    run_id = os.environ.get("GITHUB_RUN_ID")
    run_url = f"{server}/{repo_name}/actions/runs/{run_id}" if run_id else None
    return GitHubOutput(repo, repo.default_branch, run_url)


@app.command()
def action(
    working_directory: Annotated[
        Path, typer.Option(envvar="DRIFTPILOT_WORKING_DIRECTORY", help="Terraform folder.")
    ] = Path("."),
    config_path: Annotated[
        Path, typer.Option(envvar="DRIFTPILOT_CONFIG_PATH", help="Repo config file.")
    ] = Path(".driftpilot.yml"),
    mode: Annotated[
        str | None, typer.Option(envvar="DRIFTPILOT_MODE", help="advise or open-prs.")
    ] = None,
) -> None:
    """Entry point for the GitHub Action: scan, triage, open issues/PRs, write the job summary."""
    cfg = _load(working_directory, config_path if config_path.exists() else None)
    if mode:
        cfg = cfg.model_copy(update={"mode": mode})
    result = _scan_or_exit(working_directory, cfg, use_llm=True)

    token = os.environ.get("DRIFTPILOT_GITHUB_TOKEN")
    repo_name = os.environ.get("GITHUB_REPOSITORY")
    if token and repo_name:
        try:
            output = _github_output(repo_name, token)
            result.remediations = run_remediations(
                result, cfg, build_llm(cfg.llm), working_directory, output, str(working_directory)
            )
        except Exception as e:
            result.errors.append(f"remediation: {e}")

    # CI logs have no terminal, so rich would assume 80 columns and wrap every cell.
    print_result(result, Console(width=200))
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
