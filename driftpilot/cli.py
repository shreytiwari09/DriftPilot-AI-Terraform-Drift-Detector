"""Command-line interface: `driftpilot scan | fix | report | action | version`."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from driftpilot import __version__
from driftpilot.cloud_events import CloudEvent, load_events, parse_events
from driftpilot.collector import TerraformError
from driftpilot.config import Config, load_config
from driftpilot.database.connect import DatabaseError, redact_url
from driftpilot.database.remediate import DatabaseContext, database_patch
from driftpilot.envfile import load_env_file
from driftpilot.models import Context, ScanResult
from driftpilot.remediate.runner import ConsoleOutput, run_remediations
from driftpilot.report import counts
from driftpilot.report.console import print_result
from driftpilot.report.summary import build_combined_summary
from driftpilot.scan import attach_audit, run_database_scan, run_scan
from driftpilot.triage.llm import AuditingLLM, build_llm, guarded

app = typer.Typer(help="Detect, triage and fix Terraform and database drift.", no_args_is_help=True)
db_app = typer.Typer(help="Postgres schema drift: migration files against a live database.")
app.add_typer(db_app, name="db", no_args_is_help=True)
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


def _make_llm(config: Config, use_llm: bool) -> AuditingLLM | None:
    """The configured LLM with the run's budget and audit trail, shared by scan and fixes."""
    llm = guarded(build_llm(config.llm), config.limits) if use_llm else None
    if use_llm and llm is None and config.llm.enabled:
        err_console.print("[dim]No LLM API key found: undecided findings stay 'needs triage'.[/]")
    return llm


def _scan_or_exit(
    working_dir: Path,
    config: Config,
    llm: AuditingLLM | None,
    plan_json: Path | None = None,
    state_json: Path | None = None,
    events: list[CloudEvent] | None = None,
) -> ScanResult:
    try:
        return run_scan(
            working_dir, config, plan_json=plan_json, state_json=state_json, llm=llm, events=events
        )
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
    history: Annotated[
        Path | None, typer.Option(help="Append this scan to a local history folder.")
    ] = None,
    event: Annotated[
        Path | None,
        typer.Option(help="A CloudTrail event (as EventBridge delivers it): who changed what."),
    ] = None,
) -> None:
    """Check a Terraform directory for drift and unmanaged resources."""
    cfg = _load(directory, config)
    events = None
    if event is not None:
        try:
            events = load_events(event)
        except (OSError, ValueError) as e:
            err_console.print(f"[red]error:[/] {e}")
            raise typer.Exit(1) from e
    result = _scan_or_exit(directory, cfg, _make_llm(cfg, use_llm), plan_json, state_json, events)
    if history is not None:
        from driftpilot.history.store import LocalStore, append_scan

        append_scan(LocalStore(history), result)
    if json_output:
        print(result.model_dump_json(indent=2))
    else:
        print_result(result, console, show_noise)
    if fail_on_drift and (result.real_findings or result.unmanaged):
        raise typer.Exit(2)


@app.command()
def report(
    history: Annotated[Path, typer.Option(help="History folder (drift-events.jsonl, runs.jsonl).")],
    html: Annotated[
        Path | None,
        typer.Option(help="Also write the dashboard (index.html and data.json) to this folder."),
    ] = None,
    csv_file: Annotated[
        Path | None, typer.Option("--csv", help="Also write the drift episodes to a CSV file.")
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
    note: Annotated[str | None, typer.Option(help="Banner text on the dashboard.")] = None,
    config: ConfigOption = None,
) -> None:
    """Analyze drift history: recurring drift, anomalies, shifts, health, verdict monitor."""
    from driftpilot.history.analytics import analyze, episodes_frame
    from driftpilot.history.store import LocalStore
    from driftpilot.history.verdict_monitor import monitor
    from driftpilot.report.console import print_history
    from driftpilot.report.dashboard import build_dashboard
    from driftpilot.report.dashboard.data import episode_records, episodes_csv

    publish_addresses = _load(Path("."), config).dashboard.publish_addresses

    store = LocalStore(history)
    events, runs = store.load_events(), store.load_runs()
    analytics = analyze(events, runs)
    episodes = episodes_frame(events, runs)
    mon = (
        monitor(episodes, analytics.period_end) if analytics.period_end else monitor(episodes, None)
    )
    if json_output:
        print(
            json.dumps(
                {"analytics": analytics.model_dump(mode="json"), "monitor": mon.model_dump()}
            )
        )
    else:
        print_history(analytics, mon, console)
    if html is not None:
        html.mkdir(parents=True, exist_ok=True)
        files = build_dashboard(
            analytics, mon, episodes, runs, note=note, publish_addresses=publish_addresses
        )
        for name, text in files.items():
            (html / name).write_text(text)
        console.print(f"[green]Dashboard written to {html / 'index.html'} (and data.json)[/]")
    if csv_file is not None:
        csv_file.parent.mkdir(parents=True, exist_ok=True)
        csv_file.write_text(episodes_csv(episode_records(episodes, publish_addresses)))
        console.print(f"[green]Episodes written to {csv_file}[/]")


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
    llm = _make_llm(cfg, True)
    result = _scan_or_exit(directory, cfg, llm)
    if finding:
        keep = {finding}
        result.findings = [f for f in result.findings if f.id in keep]
        result.unmanaged = [u for u in result.unmanaged if u.id in keep]
        if not result.findings and not result.unmanaged:
            err_console.print(f"[red]error:[/] no real drift with finding ID {finding}")
            raise typer.Exit(1)
    output = ConsoleOutput(console, write_to=directory if write else None)
    outcomes = run_remediations(result, cfg, llm, directory, output)
    attach_audit(result, llm)
    if not outcomes:
        console.print("[green]Nothing to fix.[/]")
    for error in result.errors:
        console.print(f"[red]error:[/] {error}")


ExpectedJson = Annotated[
    Path | None,
    typer.Option(help="Replay a saved catalog of what the migrations build (see `db catalog`)."),
]
LiveJson = Annotated[Path | None, typer.Option(help="Replay a saved catalog of the live database.")]


def _database_scan_or_exit(
    directory: Path,
    config: Config,
    llm: AuditingLLM | None,
    expected_json: Path | None,
    live_json: Path | None,
):
    from driftpilot.database.scan import load_catalogs

    try:
        catalogs = load_catalogs(directory, config, expected_json, live_json)
        result = run_database_scan(directory, config, llm, catalogs=catalogs)
    except (DatabaseError, OSError, ValueError) as e:
        err_console.print(f"[red]error:[/] {redact_url(str(e))}")
        raise typer.Exit(1) from e
    return result, catalogs


@db_app.command("scan")
def db_scan(
    directory: DirOption = Path("."),
    config: ConfigOption = None,
    use_llm: LLMOption = True,
    json_output: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
    show_noise: Annotated[
        bool, typer.Option(help="Also list findings rules marked as noise.")
    ] = False,
    expected_json: ExpectedJson = None,
    live_json: LiveJson = None,
    fail_on_drift: Annotated[
        bool, typer.Option(help="Exit with code 2 if real drift is found.")
    ] = False,
    history: Annotated[
        Path | None, typer.Option(help="Append this scan to a local history folder.")
    ] = None,
) -> None:
    """Compare the migration files with a live Postgres database (read-only).

    The URLs come from DRIFTPILOT_DB_URL (a read-only login) and DRIFTPILOT_SCRATCH_DB_URL (a
    login that may create scratch databases); the variable names can be changed in the config.
    """
    cfg = _load(directory, config)
    result, _ = _database_scan_or_exit(
        directory, cfg, _make_llm(cfg, use_llm), expected_json, live_json
    )
    if history is not None:
        from driftpilot.history.store import LocalStore, append_scan

        append_scan(LocalStore(history), result)
    if json_output:
        print(result.model_dump_json(indent=2))
    else:
        print_result(result, console, show_noise)
    if fail_on_drift and result.real_findings:
        raise typer.Exit(2)


@db_app.command("fix")
def db_fix(
    directory: DirOption = Path("."),
    config: ConfigOption = None,
    finding: Annotated[
        str | None, typer.Option(help="Only the object with this finding ID (see --json).")
    ] = None,
    write: Annotated[
        bool, typer.Option("--write/--dry-run", help="Write verified migrations to the folder.")
    ] = False,
    use_llm: LLMOption = True,
    expected_json: ExpectedJson = None,
    live_json: LiveJson = None,
) -> None:
    """Show the issues and pull requests DriftPilot would open for database drift.

    Reverts show suggested SQL (never run by DriftPilot); changes worth keeping get a new
    migration file that is tested in a scratch database. Never calls GitHub.
    """
    from driftpilot.database.scan import scratch_url

    cfg = _load(directory, config).model_copy(update={"mode": "open-prs"})
    llm = _make_llm(cfg, use_llm)
    result, catalogs = _database_scan_or_exit(directory, cfg, llm, expected_json, live_json)
    ctx = DatabaseContext(
        working_dir=directory,
        config=cfg,
        live=catalogs.live.filtered(cfg.database.ignore),
        scratch_url=scratch_url(cfg),
        baseline_ids={f.id for f in result.real_findings},
    )
    if finding:
        result.findings = [f for f in result.findings if f.id == finding]
        if not result.findings:
            err_console.print(f"[red]error:[/] no database drift with finding ID {finding}")
            raise typer.Exit(1)
    output = ConsoleOutput(console, write_to=directory if write else None)
    outcomes = run_remediations(
        result, cfg, llm, directory, output, db_patch=lambda item: database_patch(item, ctx)
    )
    if not outcomes:
        console.print("[green]Nothing to fix.[/]")
    for error in result.errors:
        console.print(f"[red]error:[/] {redact_url(error)}")


@db_app.command("catalog")
def db_catalog(
    out: Annotated[Path, typer.Option(help="Where to write the catalog JSON.")],
    source: Annotated[
        str, typer.Option(help="`live` (the database) or `migrations` (what they build).")
    ] = "live",
    directory: DirOption = Path("."),
    config: ConfigOption = None,
) -> None:
    """Save a catalog as JSON, to replay later with --expected-json / --live-json."""
    from driftpilot.database.catalog import read_catalog, save_catalog
    from driftpilot.database.connect import url_from_env
    from driftpilot.database.expected import build_expected, read_migrations

    cfg = _load(directory, config)
    db, env = cfg.database, dict(os.environ)
    try:
        if source == "live":
            catalog = read_catalog(url_from_env(db.url_env, env), db.schemas, db.ignore)
        elif source == "migrations":
            files = read_migrations(directory / db.migrations)
            scratch = url_from_env(db.scratch_url_env, env)
            catalog = build_expected(scratch, files, db.schemas, db.ignore)
        else:
            err_console.print("[red]error:[/] --source must be `live` or `migrations`")
            raise typer.Exit(1)
        out.parent.mkdir(parents=True, exist_ok=True)
        save_catalog(catalog, out)
    except (DatabaseError, OSError) as e:
        err_console.print(f"[red]error:[/] {redact_url(str(e))}")
        raise typer.Exit(1) from e
    console.print(f"[green]Wrote {len(catalog.tables)} table(s) to {out}[/]")


def _github_output(repo_name: str, token: str):
    from github import Auth, Github

    from driftpilot.remediate.github_out import GitHubOutput

    repo = Github(auth=Auth.Token(token)).get_repo(repo_name)
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    run_id = os.environ.get("GITHUB_RUN_ID")
    run_url = f"{server}/{repo_name}/actions/runs/{run_id}" if run_id else None
    return GitHubOutput(repo, repo.default_branch, run_url)


def _learn_and_publish(
    result: ScanResult, output, branch: str, cfg: Config, publish: bool = True
) -> str:
    """Record history, update outcomes, monitor, publish the dashboard; return summary markdown.

    `publish=False` records the run but leaves the dashboard to a later call (one per action run).
    """
    from driftpilot.history.learn import dashboard_files, learn, publish_dashboard
    from driftpilot.history.store import GitHubBranchStore

    learned = learn(GitHubBranchStore(output.repo, branch), result, output.repo, output)
    h = learned.analytics.health
    lines = [
        "",
        "### History",
        "",
        f"{h.runs} runs recorded on `{branch}` · {learned.analytics.episodes} drift episodes · "
        f"{h.pct_runs_zero_drift}% runs clean · "
        f"{learned.outcomes_updated} human outcome(s) updated.",
    ]
    for alert in learned.monitor.alerts:
        lines.append(f"- ⚠️ {alert}")
    if learned.alert_url:
        lines.append(f"- Review issue: {learned.alert_url}")
    dashboard_repo = os.environ.get("DRIFTPILOT_DASHBOARD_REPO")
    dashboard_token = os.environ.get("DRIFTPILOT_DASHBOARD_TOKEN")
    if publish and dashboard_repo and dashboard_token:
        files = dashboard_files(
            learned, f"DriftPilot — {output.repo.full_name}", None, cfg.dashboard.publish_addresses
        )
        url = publish_dashboard(
            files, dashboard_repo, dashboard_token, f"Update dashboard ({result.run_id})"
        )
        lines.append(f"- Dashboard: {url}")
    return "\n".join(lines) + "\n"


CHECKS = ("infrastructure", "database")


def _parse_checks(text: str) -> list[str]:
    checks = [c.strip() for c in text.split(",") if c.strip()] or ["infrastructure"]
    unknown = [c for c in checks if c not in CHECKS]
    if unknown:
        err_console.print(
            f"[red]error:[/] unknown check {unknown[0]!r} (allowed: {', '.join(CHECKS)})"
        )
        raise typer.Exit(1)
    return checks


def _action_events(path: Path | None, text: str | None) -> tuple[list[CloudEvent], list[str]]:
    """Cloud events for the action, from a file or JSON text; a bad one is reported, not fatal."""
    try:
        if path is not None:
            return load_events(path), []
        if text:
            return parse_events(text, "DRIFTPILOT_EVENT_JSON"), []
    except (OSError, ValueError) as e:
        return [], [f"event: {e}"]
    return [], []


def _write_outputs(results: list[ScanResult]) -> None:
    """Action outputs: GitHub's file when running there, else driftpilot-outputs.json."""
    all_counts = [counts(r) for r in results]
    values = {
        "drift-found": "true" if any(r.real_findings or r.unmanaged for r in results) else "false",
        "critical-count": str(sum(c["critical"] for c in all_counts)),
        "finding-count": str(sum(len(r.real_findings) for r in results)),
        "unmanaged-count": str(sum(c["unmanaged"] for c in all_counts)),
    }
    if path := os.environ.get("GITHUB_OUTPUT"):
        with open(path, "a") as f:
            f.writelines(f"{key}={value}\n" for key, value in values.items())
    else:
        target = Path(os.environ.get("DRIFTPILOT_OUTPUTS_FILE", "driftpilot-outputs.json"))
        run_ids = ",".join(r.run_id for r in results)
        target.write_text(json.dumps({**values, "run-id": run_ids}, indent=2) + "\n")


def _database_section(
    working_directory: Path, cfg: Config, llm: AuditingLLM | None, audit_since: int
) -> tuple[ScanResult, DatabaseContext | None]:
    """The database check of `action`: a scan result, never an exception.

    Without a URL, or if the database cannot be read, the section carries the error instead.
    """
    from driftpilot.database.scan import load_catalogs, scratch_url

    try:
        catalogs = load_catalogs(working_directory, cfg)
        result = run_database_scan(
            working_directory, cfg, llm, catalogs=catalogs, audit_since=audit_since
        )
    except (DatabaseError, OSError, ValueError) as e:
        now = datetime.now(UTC)
        failed = ScanResult(
            run_id=f"{now:%Y%m%dT%H%M%SZ}-db",
            started_at=now,
            working_dir=str(working_directory),
            context=Context(drift_type="database"),
            errors=[f"database: {redact_url(str(e))}"],
        )
        return failed, None
    ctx = DatabaseContext(
        working_dir=working_directory,
        config=cfg,
        live=catalogs.live.filtered(cfg.database.ignore),
        scratch_url=scratch_url(cfg),
        baseline_ids={f.id for f in result.real_findings},
    )
    return result, ctx


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
    checks: Annotated[
        str,
        typer.Option(envvar="DRIFTPILOT_CHECKS", help="Comma list: infrastructure, database."),
    ] = "infrastructure",
    event: Annotated[
        Path | None,
        typer.Option(
            "--event",
            "--event-path",
            envvar="DRIFTPILOT_EVENT_PATH",
            help="A CloudTrail event file (who changed what).",
        ),
    ] = None,
    migrations_dir: Annotated[
        str | None,
        typer.Option(
            envvar="DRIFTPILOT_MIGRATIONS_DIR", help="Migrations folder (database check)."
        ),
    ] = None,
) -> None:
    """Entry point for the GitHub Action and the cloud runner.

    Scans, triages, opens issues/PRs, and writes the summary and outputs: to GitHub's files when
    run by GitHub Actions, else the summary is printed and outputs go to driftpilot-outputs.json.
    The database check reads the URLs from the environment (DRIFTPILOT_DB_URL and
    DRIFTPILOT_SCRATCH_DB_URL) and never prints them.
    """
    selected = _parse_checks(checks)
    cfg = _load(working_directory, config_path if config_path.exists() else None)
    if mode:
        cfg = cfg.model_copy(update={"mode": mode})
    if migrations_dir:
        database = cfg.database.model_copy(update={"migrations": migrations_dir})
        cfg = cfg.model_copy(update={"database": database})
    llm = _make_llm(cfg, True)
    token = os.environ.get("DRIFTPILOT_GITHUB_TOKEN")
    repo_name = os.environ.get("GITHUB_REPOSITORY")

    output = None
    output_error = None
    if token and repo_name:
        try:
            output = _github_output(repo_name, token)
        except Exception as e:
            output_error = f"remediation: {redact_url(str(e))}"

    sections: list[tuple[str, ScanResult]] = []
    contexts: dict[str, DatabaseContext] = {}
    used = 0  # LLM calls already recorded in an earlier section's audit

    def finish(title: str, result: ScanResult, ctx: DatabaseContext | None = None) -> None:
        """Open issues/PRs for one section and record its share of the LLM audit trail."""
        nonlocal used, output_error
        patcher = (lambda item: database_patch(item, ctx)) if ctx else None
        if output is not None and (ctx is not None or _is_infra(result)):
            try:
                result.remediations = run_remediations(
                    result, cfg, llm, working_directory, output, str(working_directory),
                    db_patch=patcher,
                )  # fmt: skip
            except Exception as e:
                result.errors.append(f"remediation: {redact_url(str(e))}")
        if output_error:
            result.errors.append(output_error)
            output_error = None
        attach_audit(result, llm, used)  # includes the calls the fixes made
        used = len(llm.records) if llm else 0
        sections.append((title, result))
        if ctx is not None:
            contexts[result.run_id] = ctx

    if "infrastructure" in selected:
        events, event_errors = _action_events(event, os.environ.get("DRIFTPILOT_EVENT_JSON"))
        result = _scan_or_exit(working_directory, cfg, llm, events=events)
        result.errors += event_errors
        finish("Infrastructure drift (Terraform)", result)
    if "database" in selected:
        result, ctx = _database_section(working_directory, cfg, llm, used)
        finish("Database drift (Postgres)", result, ctx)

    history_md = ""
    branch = os.environ.get("DRIFTPILOT_HISTORY_BRANCH")
    if output is not None and branch:
        recorded = [r for _, r in sections if r.run_id in contexts or _is_infra(r)]
        for n, result in enumerate(recorded):
            try:
                history_md = _learn_and_publish(
                    result, output, branch, cfg, publish=n == len(recorded) - 1
                )
            except Exception as e:  # learning must never hide this run's drift report
                result.errors.append(f"history: {redact_url(str(e))}")

    # CI logs have no terminal, so rich would assume 80 columns and wrap every cell.
    wide = Console(width=200)
    for title, result in sections:
        if len(sections) > 1:
            wide.rule(title)
        print_result(result, wide)
    summary = build_combined_summary(sections) + history_md
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(path, "a") as f:
            f.write(summary)
    else:
        print(summary)

    results = [r for _, r in sections]
    _write_outputs(results)
    if critical := sum(counts(r)["critical"] for r in results):
        if os.environ.get("GITHUB_ACTIONS") or os.environ.get("GITHUB_OUTPUT"):
            # annotation shown at the top of the workflow run page
            print(f"::error title=DriftPilot::{critical} critical drift finding(s)")
        else:
            print(f"DriftPilot: {critical} critical drift finding(s)")


def _is_infra(result: ScanResult) -> bool:
    return result.context.drift_type == "infrastructure"


@app.command()
def version() -> None:
    """Show the DriftPilot version."""
    print(__version__)
