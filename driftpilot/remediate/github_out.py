"""Open or update GitHub issues and PRs for remediation plans (SPEC §4.5).

One open issue/PR per plan key; a hidden marker in the body finds it again on later runs.
"""

import posixpath
import re
from dataclasses import dataclass
from typing import Any, Protocol

from driftpilot.models import DriftFinding, UnmanagedFinding, Verdict
from driftpilot.remediate.codify import Patch
from driftpilot.triage.policy import RemediationPlan
from driftpilot.triage.rules import needs_replace_to_revert

LABELS = {
    "driftpilot": ("1d76db", "Opened by DriftPilot"),
    "severity:critical": ("b60205", "Critical drift"),
    "severity:high": ("d93f0b", "High-severity drift"),
    "severity:medium": ("fbca04", "Medium-severity drift"),
    "severity:low": ("0e8a16", "Low-severity drift"),
    "unverified": ("cccccc", "Proposed change did not pass Terraform verification"),
}
ACTION_TEXT = {
    "revert": "Undo the hand change so reality matches the code again.",
    "recreate": "The resource was deleted outside Terraform; recreate it from the code.",
    "investigate": "A person should decide whether to keep this change or undo it.",
    "codify": "Keep the change and update the code to match it.",
    "ignore_changes": "Stop Terraform from managing this setting (`lifecycle.ignore_changes`).",
    "import": "Bring this resource under Terraform so its settings get reviewed too.",
}


def marker(key: str) -> str:
    return f"<!-- driftpilot:key={key} -->"


@dataclass
class Item:
    """Everything needed to describe one plan to a human."""

    plan: RemediationPlan
    findings: list[DriftFinding]
    unmanaged: list[UnmanagedFinding]
    verdicts: dict[str, Verdict]
    working_dir: str  # relative to the repo root, e.g. "infra"


class Output(Protocol):
    def issue(self, item: Item, patch: Patch | None = None) -> str: ...

    def pull_request(self, item: Item, patch: Patch) -> str: ...


def _cell(value: Any) -> str:
    text = str(value) if not isinstance(value, str) else value
    text = text if len(text) <= 80 else text[:79] + "…"
    return text.replace("|", "\\|").replace("\n", " ")


def _changes_table(item: Item) -> str:
    rows = ["| Setting | Recorded → Real | Why | Source |", "| --- | --- | --- | --- |"]
    for f in item.findings:
        v = item.verdicts.get(f.id)
        change = (
            "deleted" if f.change_kind == "deleted" else f"`{_cell(f.before)}` → `{_cell(f.after)}`"
        )
        source = f"{v.source} · {v.intent} · {v.confidence:.0%}" if v else "—"
        reason = _cell(v.reason) if v else ""
        rows.append(f"| `{f.attribute_path or '—'}` | {change} | {reason} | {source} |")
    for u in item.unmanaged:
        v = item.verdicts.get(u.id)
        rows.append(
            f"| {u.resource_kind} `{_cell(u.name)}` | not in Terraform "
            f"| {_cell(v.reason if v else '')} | policy |"
        )
    return "\n".join(rows)


def revert_command(item: Item, working_dir: str) -> str:
    flag = "-replace" if any(needs_replace_to_revert(f) for f in item.findings) else "-target"
    cd = f"cd {working_dir} && " if working_dir not in ("", ".") else ""
    return f"{cd}terraform apply {flag}={item.plan.address}"


def _patch_section(patch: Patch) -> str:
    files = "\n\n".join(
        f"`{path}`\n```hcl\n{content.strip()}\n```" for path, content in patch.files.items()
    )
    status = "✅ verified" if patch.verified else "⚠️ **not verified** — do not apply without review"
    return (
        f"### Proposed change ({status}, {patch.attempts} attempt(s))\n\n{files}\n\n"
        "<details><summary>Terraform output</summary>\n\n"
        f"```\n{patch.proof.strip()}\n```\n</details>"
    )


def issue_body(item: Item, patch: Patch | None, run_url: str | None) -> str:
    p = item.plan
    lines = [
        marker(p.key),
        f"**Severity:** {p.severity} · **Recommended action:** `{p.action}` — "
        f"{ACTION_TEXT[p.action]}",
        "",
        f"### What changed on `{p.address}`",
        "",
        _changes_table(item),
    ]
    if p.action in ("revert", "recreate"):
        lines += [
            "",
            "### How to fix",
            "",
            "```bash",
            revert_command(item, item.working_dir),
            "```",
        ]
    if patch is not None:
        lines += ["", _patch_section(patch)]
    lines += ["", f"_Opened by DriftPilot{f' ([run]({run_url}))' if run_url else ''}._"]
    return "\n".join(lines)


def pr_body(item: Item, patch: Patch, run_url: str | None) -> str:
    p = item.plan
    proof = patch.proof.strip()
    return "\n".join(
        [
            marker(p.key),
            f"**Action:** `{p.action}` — {ACTION_TEXT[p.action]} · **Severity:** {p.severity}",
            "",
            f"### What changed on `{p.address}`",
            "",
            _changes_table(item),
            "",
            "### Proof",
            "",
            f"`terraform plan` for `{p.address}` with this change "
            f"({patch.attempts} attempt(s), {patch.note}):",
            "",
            f"```\n{proof}\n```",
            "",
            "After merging, run `terraform apply`: no infrastructure change is expected; "
            "it records the current values in Terraform's state.",
            "",
            f"_Opened by DriftPilot{f' ([run]({run_url}))' if run_url else ''}._",
        ]
    )


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


class GitHubOutput:
    """Writes to one repository with PyGithub (`repo` is a github.Repository)."""

    def __init__(self, repo: Any, base_branch: str, run_url: str | None = None) -> None:
        self.repo = repo
        self.base = base_branch
        self.run_url = run_url
        self._labels_ready = False

    def _ensure_labels(self) -> None:
        if self._labels_ready:
            return
        existing = {label.name for label in self.repo.get_labels()}
        for name, (color, description) in LABELS.items():
            if name not in existing:
                self.repo.create_label(name, color, description)
        self._labels_ready = True

    def _find_open(self, key: str) -> Any | None:
        tag = marker(key)
        for issue in self.repo.get_issues(state="open", labels=["driftpilot"]):
            if tag in (issue.body or ""):
                return issue
        return None

    def _labels(self, item: Item, patch: Patch | None) -> list[str]:
        labels = ["driftpilot", f"severity:{item.plan.severity}"]
        if patch is not None and not patch.verified:
            labels.append("unverified")
        return [label for label in labels if label in LABELS]

    def issue(self, item: Item, patch: Patch | None = None) -> str:
        self._ensure_labels()
        body = issue_body(item, patch, self.run_url)
        existing = self._find_open(item.plan.key)
        if existing is not None:
            existing.edit(body=body)
            existing.create_comment(
                f"Still drifting{f' as of [this run]({self.run_url})' if self.run_url else ''}."
            )
            return existing.html_url
        title = f"[DriftPilot] {item.plan.severity} drift: {item.plan.address} ({item.plan.action})"
        return self.repo.create_issue(
            title=title, body=body, labels=self._labels(item, patch)
        ).html_url

    def pull_request(self, item: Item, patch: Patch) -> str:
        self._ensure_labels()
        branch = f"driftpilot/{item.plan.action}-{_slug(item.plan.address)}"
        base_sha = self.repo.get_branch(self.base).commit.sha
        existing = self._find_open(item.plan.key)
        if existing is None:
            self.repo.create_git_ref(ref=f"refs/heads/{branch}", sha=base_sha)
        message = f"DriftPilot: {item.plan.action} {item.plan.address}"
        for rel, content in patch.files.items():
            path = posixpath.normpath(posixpath.join(item.working_dir or ".", rel))
            try:
                current = self.repo.get_contents(path, ref=branch)
                self.repo.update_file(path, message, content, current.sha, branch=branch)
            except Exception as e:  # PyGithub raises UnknownObjectException for a new file
                if getattr(e, "status", None) != 404:
                    raise
                self.repo.create_file(path, message, content, branch=branch)
        body = pr_body(item, patch, self.run_url)
        if existing is not None:
            existing.edit(body=body)
            existing.create_comment("Updated with a newly verified change.")
            return existing.html_url
        title = f"[DriftPilot] {item.plan.action} {item.plan.address}"
        pr = self.repo.create_pull(base=self.base, head=branch, title=title, body=body)
        pr.add_to_labels(*self._labels(item, patch))
        return pr.html_url
