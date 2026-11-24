"""Turn a scan's verdicts into fixes: plan per resource → patch → PR, or an issue (SPEC §4.5)."""

import difflib
from collections.abc import Callable
from pathlib import Path

from rich.console import Console

from driftpilot.config import Config
from driftpilot.models import GuardrailEvent, RemediationResult, ScanResult
from driftpilot.remediate.codify import Patch, codify, ignore_changes
from driftpilot.remediate.github_out import Item, Output, is_database, issue_body, pr_body
from driftpilot.remediate.importer import import_resource
from driftpilot.scanners import import_target
from driftpilot.triage.llm import LLMClient
from driftpilot.triage.policy import RemediationPlan, plan_remediations

DatabasePatcher = Callable[[Item], Patch | None]


def make_patch(
    plan: RemediationPlan,
    item: Item,
    llm: LLMClient | None,
    working_dir: Path,
    config: Config,
    db_patch: DatabasePatcher | None = None,
) -> Patch | None:
    """A verified-or-not patch for PR actions; None when no patch can be attempted."""
    if is_database(item):  # a Postgres schema: the patch is a migration file, not Terraform
        return db_patch(item) if db_patch else None
    if plan.action == "codify":
        if llm is None:
            return None
        return codify(
            llm, working_dir, item.findings, config.max_codify_retries, config.guardrails.enabled
        )
    if plan.action == "ignore_changes":
        return ignore_changes(working_dir, item.findings)
    if plan.action == "import" and item.unmanaged:
        target = import_target(item.unmanaged[0])
        if target is None:
            return None
        return import_resource(
            llm,
            working_dir,
            target,
            config.max_codify_retries,
            config.guardrails.enabled,
            [u.id for u in item.unmanaged],
        )
    return None


def changed_lines(working_dir: Path, files: dict[str, str]) -> int:
    """Lines added or removed by a patch, compared with the files as they are now."""
    total = 0
    for rel, new in files.items():
        path = working_dir / rel
        old = path.read_text().splitlines() if path.exists() else []
        diff = difflib.unified_diff(old, new.splitlines(), n=0, lineterm="")
        total += sum(1 for line in diff if line[0] in "+-" and line[:3] not in ("+++", "---"))
    return total


def enforce_patch_limits(
    patch: Patch, working_dir: Path, config: Config, events: list[GuardrailEvent], key: str
) -> None:
    """A patch bigger than the limits is not reviewed-in-a-glance size: make it unverified."""
    limits = config.limits
    lines = changed_lines(working_dir, patch.files)
    if len(patch.files) <= limits.max_files_per_pr and lines <= limits.max_patch_lines:
        return
    detail = (
        f"patch too large: {len(patch.files)} files, {lines} changed lines "
        f"(limits {limits.max_files_per_pr} files, {limits.max_patch_lines} lines)"
    )
    patch.verified, patch.files = False, {}
    patch.note = f"guardrail: {detail}; review the change by hand"
    events.append(GuardrailEvent(kind="patch-too-large", detail=f"{key}: {detail}"))


def run_remediations(
    result: ScanResult,
    config: Config,
    llm: LLMClient | None,
    working_dir: Path,
    output: Output,
    repo_working_dir: str = ".",
    db_patch: DatabasePatcher | None = None,
) -> list[RemediationResult]:
    """Open/update one issue or PR per plan. A failing plan is recorded, not fatal.

    `db_patch` writes the patch for a database item (a verified migration file).
    """
    outcomes = []
    prs_tried = 0
    for plan in plan_remediations(result.findings, result.unmanaged, result.verdicts, config):
        ids = set(plan.finding_ids)
        item = Item(
            plan=plan,
            findings=[f for f in result.findings if f.id in ids],
            unmanaged=[u for u in result.unmanaged if u.id in ids],
            verdicts=result.verdicts,
            working_dir=repo_working_dir,
        )
        if plan.delivery == "pr" and prs_tried >= config.limits.max_prs:
            item.plan = plan = plan.model_copy(update={"delivery": "issue"})
            detail = f"{plan.key}: more than {config.limits.max_prs} PR(s) in one run"
            result.guardrail_events.append(GuardrailEvent(kind="pr-limit", detail=detail))
        elif plan.delivery == "pr":
            prs_tried += 1
        try:
            patch = (
                make_patch(plan, item, llm, working_dir, config, db_patch)
                if plan.delivery == "pr"
                else None
            )
            if patch is not None:
                enforce_patch_limits(patch, working_dir, config, result.guardrail_events, plan.key)
            if patch is not None and patch.verified:
                pr_url, issue_url = output.pull_request(item, patch), None
            else:  # issues, plus PR actions whose patch couldn't be verified
                pr_url, issue_url = None, output.issue(item, patch)
        except Exception as e:  # one failure shouldn't stop the other plans
            result.errors.append(f"remediation {plan.key}: {e}")
            continue
        outcomes.append(
            RemediationResult(
                finding_id=plan.finding_ids[0],
                finding_ids=plan.finding_ids,
                action=plan.action,
                verified=bool(patch and patch.verified),
                attempts=patch.attempts if patch else 0,
                pr_url=pr_url,
                issue_url=issue_url,
                plan_proof=patch.proof if patch and patch.verified else None,
            )
        )
    return outcomes


class ConsoleOutput:
    """Prints what would be opened instead of calling GitHub (`driftpilot fix`).

    With `write_to`, verified patches are also written into that directory (`--write`).
    """

    def __init__(self, console: Console, write_to: Path | None = None) -> None:
        self.console = console
        self.write_to = write_to

    def issue(self, item: Item, patch: Patch | None = None) -> str:
        self.console.rule(f"[bold]Issue[/]: {item.plan.address} ({item.plan.action})")
        self.console.print(issue_body(item, patch, None), markup=False)
        return "(dry run: issue)"

    def pull_request(self, item: Item, patch: Patch) -> str:
        self.console.rule(f"[bold green]Pull request[/]: {item.plan.address} ({item.plan.action})")
        self.console.print(pr_body(item, patch, None), markup=False)
        for path, content in patch.files.items():
            self.console.rule(path)
            self.console.print(content, markup=False)
            if self.write_to is not None:
                (self.write_to / path).parent.mkdir(parents=True, exist_ok=True)
                (self.write_to / path).write_text(content)
                self.console.print(f"[green]wrote {self.write_to / path}[/]")
        return "(dry run: pull request)" if self.write_to is None else "(written locally)"
