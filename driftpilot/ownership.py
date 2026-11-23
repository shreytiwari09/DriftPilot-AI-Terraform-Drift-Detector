"""Who owns a finding, and which repo / environment / account it belongs to.

Team, first hit wins: a resource tag, a `.driftpilot.yml` rule, CODEOWNERS, the default team,
then "unowned". Everything shown on the dashboard is cleaned first: tags are text others can write.
"""

import os
import re
from pathlib import Path
from typing import Any

from driftpilot.config import Config
from driftpilot.guardrails import sanitize_text
from driftpilot.hcl import find_owner_block
from driftpilot.models import Context, DriftFinding, ScanResult, UnmanagedFinding
from driftpilot.triage.rules import glob_match

UNOWNED = "unowned"
TEAM_TAGS = ("team", "owner")
CODEOWNERS_PATHS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")
_ACCOUNT_ID = re.compile(r"(?<!\d)\d{12}(?!\d)")
_ARN = re.compile(r"arn:aws[\w-]*:[^\s\"',;]+")


def mask_ids(text: str | None) -> str | None:
    """Hide AWS ARNs and 12-digit account IDs, so history and dashboards never carry them."""
    if text is None:
        return None
    return _ACCOUNT_ID.sub("*" * 12, _ARN.sub("arn:***", text))


def clean_label(value: Any, limit: int = 40) -> str | None:
    """A short, safe label from text someone else may have written (None if nothing is left)."""
    if not isinstance(value, str):
        return None
    text = sanitize_text(value).strip()
    if not text:
        return None
    return text if len(text) <= limit else text[:limit] + "…"


def team_from_tags(values: Any) -> str | None:
    """`tags.team`, else `tags.owner`, from a resource's values."""
    tags = values.get("tags") if isinstance(values, dict) else None
    if not isinstance(tags, dict):
        return None
    for key in TEAM_TAGS:
        if label := clean_label(tags.get(key)):
            return label
    return None


def _codeowners_regex(pattern: str) -> re.Pattern[str]:
    """CODEOWNERS pattern (gitignore style) to a regex over repo-relative POSIX paths."""
    anchored = pattern.startswith("/") or "/" in pattern.rstrip("/")
    body, out, i = pattern.strip("/"), "", 0
    while i < len(body):
        if body.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif body.startswith("**", i):
            out, i = out + ".*", i + 2
        elif body[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif body[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(body[i]), i + 1
    start = "^" if anchored else "^(?:.*/)?"
    end = "/.*$" if pattern.endswith("/") else "(?:/.*)?$"
    return re.compile(start + out + end)


def _team_from_owner(token: str) -> str | None:
    name = token.lstrip("@")
    name = name.split("/")[-1] if "/" in name else name.split("@")[0]
    return clean_label(name)


def find_codeowners(start: Path) -> tuple[Path, Path] | None:
    """(repo root, CODEOWNERS file): looks in `start` and up to three parent folders."""
    folder = start.resolve()
    for root in [folder, *folder.parents[:3]]:
        for name in CODEOWNERS_PATHS:
            if (root / name).is_file():
                return root, root / name
    return None


def codeowners_team(root: Path, path: Path, file: Path | None = None) -> str | None:
    """The team CODEOWNERS gives `path` (the last matching line wins), or None."""
    file = file or next((root / n for n in CODEOWNERS_PATHS if (root / n).is_file()), None)
    if file is None:
        return None
    try:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None
    owners: list[str] | None = None
    for line in file.read_text().splitlines():
        parts = line.split("#")[0].split()
        if len(parts) >= 1 and _codeowners_regex(parts[0]).match(relative):
            owners = parts[1:]
    return _team_from_owner(owners[0]) if owners else None


class Owner:
    """Resolves the owning team of resources in one Terraform directory."""

    def __init__(self, config: Config, working_dir: Path) -> None:
        self.config = config
        self.working_dir = working_dir
        self._codeowners = find_codeowners(working_dir)

    def team_for_address(self, address: str, values: Any = None) -> str:
        if team := team_from_tags(values):
            return team
        for rule in self.config.ownership.teams:
            if glob_match(rule.match, address):
                return clean_label(rule.team) or UNOWNED
        if self._codeowners and (found := find_owner_block(self.working_dir, address)):
            root, file = self._codeowners
            if team := codeowners_team(root, found[0].path, file):
                return team
        return clean_label(self.config.ownership.default_team) or UNOWNED

    def team_for(self, finding: DriftFinding, resources: dict[str, Any]) -> str:
        values = resources.get(finding.address)
        if values is None and finding.change_kind == "deleted":
            values = finding.before
        return self.team_for_address(finding.address, values)

    def team_for_unmanaged(self, u: UnmanagedFinding) -> str:
        return self.team_for_address(f"{u.resource_kind}.{u.name}")


def apply_ownership(
    result: ScanResult,
    config: Config,
    working_dir: Path,
    resources: dict[str, Any],
    managed: list[dict[str, Any]] | None,
    drift_type: str = "infrastructure",
) -> None:
    """Fill the run's context, the team of each finding and the managed count per team."""
    o = config.ownership
    owner = Owner(config, working_dir)
    result.context = Context(
        team=clean_label(o.default_team) or UNOWNED,
        repo=clean_label(o.repo or os.environ.get("GITHUB_REPOSITORY"), 80) or "unknown",
        environment=clean_label(o.environment) or "unknown",
        account=mask_ids(clean_label(o.account, 80)) or "unknown",
        drift_type=drift_type,
    )
    result.teams = {f.id: owner.team_for(f, resources) for f in result.findings}
    result.teams |= {u.id: owner.team_for_unmanaged(u) for u in result.unmanaged}
    by_team: dict[str, int] = {}
    for r in managed or []:
        team = owner.team_for_address(r["address"], r.get("values"))
        by_team[team] = by_team.get(team, 0) + 1
    result.managed_by_team = by_team
