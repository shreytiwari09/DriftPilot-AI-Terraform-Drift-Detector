"""Open or update GitHub issues and PRs for remediation plans (SPEC §4.5).

One open issue/PR per plan key; a hidden marker in the body finds it again on later runs.
"""

import json
import posixpath
import re
import shlex
from dataclasses import dataclass
from typing import Any, Protocol

from driftpilot.database import PROVIDER as POSTGRES
from driftpilot.database.sql import undo_script
from driftpilot.guardrails import sanitize_text
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
    "suspicious-input": ("5319e7", "Changed text looks like a prompt-injection attempt"),
}
ACTION_TEXT = {
    "revert": "Undo the hand change so reality matches the code again.",
    "recreate": "The resource was deleted outside Terraform; recreate it from the code.",
    "investigate": "A person should decide whether to keep this change or undo it.",
    "codify": "Keep the change and update the code to match it.",
    "ignore_changes": "Stop Terraform from managing this setting (`lifecycle.ignore_changes`).",
    "import": "Bring this resource under Terraform so its settings get reviewed too.",
}


DATABASE_ACTION_TEXT = {
    "revert": "Undo the hand change so the database matches the migrations again.",
    "recreate": "The object is missing from the live database; put it back.",
    "investigate": "A person should decide whether to keep this change or undo it.",
    "codify": "Keep the change and add a migration for it, so a rebuild keeps it too.",
}


def action_text(item: "Item") -> str:
    texts = DATABASE_ACTION_TEXT if is_database(item) else ACTION_TEXT
    return texts.get(item.plan.action) or ACTION_TEXT[item.plan.action]


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


def is_database(item: "Item") -> bool:
    """True when the item is about a Postgres schema, not Terraform resources."""
    return any(f.provider == POSTGRES for f in item.findings)


def _cell(value: Any) -> str:
    """One table cell: hidden characters and comments out, markdown-breaking characters escaped."""
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    text = sanitize_text(text, max_len=10_000)
    text = text if len(text) <= 80 else text[:79] + "…"
    return text.replace("|", "\\|").replace("`", "'")


def _change_cell(f: DriftFinding) -> str:
    if f.change_kind == "deleted":
        return "missing from the live database" if f.provider == POSTGRES else "deleted"
    if f.change_kind == "added":
        return f"only in the live database: `{_cell(f.after)}`"
    return f"`{_cell(f.before)}` → `{_cell(f.after)}`"


def _changes_table(item: Item) -> str:
    recorded = "Migrations → Live" if is_database(item) else "Recorded → Real"
    rows = [f"| Setting | {recorded} | Why | Source |", "| --- | --- | --- | --- |"]
    for f in item.findings:
        v = item.verdicts.get(f.id)
        change = _change_cell(f)
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


def revert_command(item: Item, working_dir: str, verb: str = "apply") -> str:
    flag = "-replace" if any(needs_replace_to_revert(f) for f in item.findings) else "-target"
    cd = f"cd {shlex.quote(working_dir)} && " if working_dir not in ("", ".") else ""
    # Quoted: module addresses like module.x.y["main"] contain brackets and quotes.
    return f"{cd}terraform {verb} {shlex.quote(f'{flag}={item.plan.address}')}"


FIX_NOTE = (
    "Run the plan first and read it: `-target` also includes what this resource depends on, so "
    "other drifted settings (for example on the same repository) can be changed too."
)


def _patch_section(patch: Patch, language: str = "hcl") -> str:
    files = "\n\n".join(
        f"`{path}`\n```{language}\n{content.strip()}\n```" for path, content in patch.files.items()
    )
    status = "✅ verified" if patch.verified else "⚠️ **not verified** — do not apply without review"
    if patch.note.startswith("guardrail:"):
        return f"### Proposed change ({status})\n\n{patch.note}"
    if language == "sql":
        problem = "" if patch.verified or not patch.note else f"\n\n{patch.note}"
        proof = f"\n\n**Proof:** {patch.proof.strip()}" if patch.proof.strip() else ""
        return f"### Proposed migration ({status}){problem}\n\n{files}{proof}"
    return (
        f"### Proposed change ({status}, {patch.attempts} attempt(s))\n\n{files}\n\n"
        "<details><summary>Terraform output</summary>\n\n"
        f"```\n{patch.proof.strip()}\n```\n</details>"
    )


def _sql_section(item: Item) -> list[str]:
    """Suggested SQL that undoes the drift on the live database (for a person to review and run)."""
    script, manual = undo_script(item.findings)
    lines = ["", "### Suggested SQL (review before running)", ""]
    if item.plan.action == "investigate":
        lines += ["If you decide to undo the change, this would do it:", ""]
    if script:
        lines += ["```sql", script, "```"]
    if manual:
        lines += ["", "No automatic SQL for: " + ", ".join(f"`{_cell(m)}`" for m in manual) + "."]
    lines += [
        "",
        "DriftPilot never changes the database. Run this yourself, in a transaction, after a look "
        "at the data it touches.",
    ]
    return lines


def _guardrail_notes(item: Item) -> list[str]:
    """A short "Guardrails" section when a guardrail changed a verdict, else nothing."""
    notes = []
    for f in item.findings:
        v = item.verdicts.get(f.id)
        if v and "never-soften" in v.guardrails:
            notes.append(
                f"- `{_cell(f.attribute_path or '—')}`: never-soften. The AI judged this less "
                "serious than a known security weakening can be, so the policy raised it."
            )
        if v and "suspicious-input" in v.guardrails:
            notes.append(
                f"- `{_cell(f.attribute_path or '—')}`: suspicious input. The changed text looks "
                "like an attempt to steer the AI. Treat the values above as untrusted, and "
                "decide it yourself."
            )
    for u in item.unmanaged:
        v = item.verdicts.get(u.id)
        if v and "suspicious-input" in v.guardrails:
            notes.append(f"- {u.resource_kind} `{_cell(u.name)}`: suspicious input in its name.")
    return ["", "### Guardrails", "", *notes] if notes else []


def _controls(item: Item) -> list[str]:
    """Compliance tags of every verdict in this item, in first-seen order."""
    tags: list[str] = []
    for f in [*item.findings, *item.unmanaged]:
        if v := item.verdicts.get(f.id):
            tags += [c for c in v.controls if c not in tags]
    return tags


def _changed_by(item: Item) -> list[str]:
    """ "Changed by ... via ..." when a cloud audit event named the resource, else nothing."""
    contexts = [c for f in [*item.findings, *item.unmanaged] if (c := f.change_context)]
    if not contexts:
        return []
    c = max(contexts, key=lambda c: c.event_time or "")
    clean = lambda text: _cell(text).replace("'", "")  # noqa: E731
    who = f"`{clean(c.actor)}`" if c.actor else "an unknown identity"
    where = f" ({clean(c.event_source)})" if c.event_source else ""
    when = f" at {clean(c.event_time)}" if c.event_time else ""
    return [f"**Changed by:** {who} via `{clean(c.event_name)}`{where}{when}"]


def _facts(item: Item) -> list[str]:
    tags = _controls(item)
    out = [f"**Compliance tags:** {', '.join(f'`{t}`' for t in tags)}"] if tags else []
    return out + _changed_by(item)


def issue_body(item: Item, patch: Patch | None, run_url: str | None) -> str:
    p = item.plan
    lines = [
        marker(p.key),
        f"**Severity:** {p.severity} · **Recommended action:** `{p.action}` — {action_text(item)}",
        *_facts(item),
        "",
        f"### What changed on `{p.address}`",
        "",
        _changes_table(item),
        *_guardrail_notes(item),
    ]
    if is_database(item):
        if p.action in ("revert", "recreate", "investigate"):
            lines += _sql_section(item)
    elif p.action in ("revert", "recreate"):
        lines += [
            "",
            "### How to fix",
            "",
            FIX_NOTE,
            "",
            "```bash",
            revert_command(item, item.working_dir, "plan") + "   # preview",
            revert_command(item, item.working_dir, "apply"),
            "```",
        ]
    if patch is not None:
        lines += ["", _patch_section(patch, "sql" if is_database(item) else "hcl")]
    lines += ["", f"_Opened by DriftPilot{f' ([run]({run_url}))' if run_url else ''}._"]
    return "\n".join(lines)


def _database_pr_body(item: Item, patch: Patch, run_url: str | None) -> str:
    p = item.plan
    files = ", ".join(f"`{path}`" for path in patch.files)
    return "\n".join(
        [
            marker(p.key),
            f"**Action:** `{p.action}` — {action_text(item)} · **Severity:** {p.severity}",
            *_facts(item),
            "",
            f"### What changed on `{p.address}`",
            "",
            _changes_table(item),
            *_guardrail_notes(item),
            "",
            "### Proof",
            "",
            f"{patch.proof.strip()}. DriftPilot built a fresh scratch database from every "
            f"migration plus {files} and compared it with the live database.",
            "",
            "### New migration",
            "",
            "\n\n".join(
                f"`{path}`\n```sql\n{content.strip()}\n```" for path, content in patch.files.items()
            ),
            "",
            "After merging, mark the new migration as applied on the live database (it already has "
            "this change); do not run it there. Other databases, such as a rebuild or a new "
            "environment, will get the change from this file.",
            "",
            f"_Opened by DriftPilot{f' ([run]({run_url}))' if run_url else ''}._",
        ]
    )


def pr_body(item: Item, patch: Patch, run_url: str | None) -> str:
    if is_database(item):
        return _database_pr_body(item, patch, run_url)
    p = item.plan
    proof = patch.proof.strip()
    return "\n".join(
        [
            marker(p.key),
            f"**Action:** `{p.action}` — {action_text(item)} · **Severity:** {p.severity}",
            *_facts(item),
            "",
            f"### What changed on `{p.address}`",
            "",
            _changes_table(item),
            *_guardrail_notes(item),
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
        if any(
            "suspicious-input" in v.guardrails
            for f in [*item.findings, *item.unmanaged]
            if (v := item.verdicts.get(f.id))
        ):
            labels.append("suspicious-input")
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

    def alert(self, key: str, title: str, body: str) -> str:
        """A de-duplicated issue that isn't about one resource, e.g. the verdict monitor."""
        self._ensure_labels()
        full = f"{marker(key)}\n{body}"
        if self.run_url:
            full += f"\n\n_Opened by DriftPilot ([run]({self.run_url}))._"
        existing = self._find_open(key)
        if existing is not None:
            existing.edit(body=full)
            return existing.html_url
        return self.repo.create_issue(title=title, body=full, labels=["driftpilot"]).html_url

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
