"""Turn a scan's verdicts into fixes: plan per resource → patch → PR, or an issue (SPEC §4.5)."""

from pathlib import Path

from rich.console import Console

from driftpilot.config import Config
from driftpilot.models import RemediationResult, ScanResult
from driftpilot.remediate.codify import Patch, codify, ignore_changes
from driftpilot.remediate.github_out import Item, Output, issue_body, pr_body
from driftpilot.remediate.importer import import_resource
from driftpilot.scanners import import_target
from driftpilot.triage.llm import LLMClient
from driftpilot.triage.policy import RemediationPlan, plan_remediations


def make_patch(
    plan: RemediationPlan, item: Item, llm: LLMClient | None, working_dir: Path, config: Config
) -> Patch | None:
    """A verified-or-not patch for PR actions; None when no patch can be attempted."""
    if plan.action == "codify":
        if llm is None:
            return None
        return codify(llm, working_dir, item.findings, config.max_codify_retries)
    if plan.action == "ignore_changes":
        return ignore_changes(working_dir, item.findings)
    if plan.action == "import" and item.unmanaged:
        target = import_target(item.unmanaged[0])
        if target is None:
            return None
        return import_resource(llm, working_dir, target, config.max_codify_retries)
    return None


def run_remediations(
    result: ScanResult,
    config: Config,
    llm: LLMClient | None,
    working_dir: Path,
    output: Output,
    repo_working_dir: str = ".",
) -> list[RemediationResult]:
    """Open/update one issue or PR per plan. A failing plan is recorded, not fatal."""
    outcomes = []
    for plan in plan_remediations(result.findings, result.unmanaged, result.verdicts, config):
        ids = set(plan.finding_ids)
        item = Item(
            plan=plan,
            findings=[f for f in result.findings if f.id in ids],
            unmanaged=[u for u in result.unmanaged if u.id in ids],
            verdicts=result.verdicts,
            working_dir=repo_working_dir,
        )
        try:
            patch = (
                make_patch(plan, item, llm, working_dir, config) if plan.delivery == "pr" else None
            )
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
    """Prints what would be opened instead of calling GitHub (`driftpilot fix --dry-run`)."""

    def __init__(self, console: Console) -> None:
        self.console = console

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
        return "(dry run: pull request)"
