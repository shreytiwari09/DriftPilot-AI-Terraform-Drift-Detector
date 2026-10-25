"""Actions behind the demo console: inject drift, watch DriftPilot on GitHub, run it locally.

Runs on the presenter's laptop. GitHub writes for the injector use the demo org's token (Keychain or
GITHUB_TOKEN); reading Actions runs, issues and PRs uses the presenter's own `gh` login.
"""

import argparse
import importlib.util
import json
import os
import re
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
ORG = "driftpilot-demo"
INFRA = f"{ORG}/infra"
DOCKER_DIR = ROOT / "demo" / "docker"
DASHBOARD = "https://driftpilot-demo.github.io/drift-dashboard/"
SIMULATED_DASHBOARD = DASHBOARD + "simulated/"
KEYCHAIN_SERVICE = "driftpilot-demo-pat"


# ---------- setup ----------


def load_credentials() -> dict[str, bool]:
    """Make the demo org token and the LLM key available to this process. Returns what was found."""
    from driftpilot.envfile import load_env_file

    load_env_file(ROOT / ".env")
    if not os.environ.get("GITHUB_TOKEN"):
        found = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True,
            text=True,
        )
        if found.returncode == 0:
            os.environ["GITHUB_TOKEN"] = found.stdout.strip()
    return {
        "Demo org token": bool(os.environ.get("GITHUB_TOKEN")),
        "Gemini key": bool(os.environ.get("GEMINI_API_KEY")),
        "gh login": _gh_ok(),
        "Docker": _docker_ok(),
    }


def _gh_ok() -> bool:
    return (
        subprocess.run(["gh", "auth", "status"], env=_gh_env(), capture_output=True).returncode == 0
    )


def _docker_ok() -> bool:
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


# ---------- drift injection (reuses scripts/inject_drift.py) ----------


def _injector() -> Any:
    spec = importlib.util.spec_from_file_location(
        "inject_drift", ROOT / "scripts" / "inject_drift.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def inject(scenario: int) -> str:
    s = _injector().SCENARIOS[scenario]
    s.inject(argparse.Namespace(tf_dir=None))
    return s.description


def revert(scenario: int, tf_dir: Path | None = None) -> str:
    s = _injector().SCENARIOS[scenario]
    s.revert(argparse.Namespace(tf_dir=tf_dir))
    return s.description


def approvals_on_github() -> int | None:
    """Current required approvals on demo-api's main branch (to show the change really happened)."""
    from github import Auth, Github

    branch = Github(auth=Auth.Token(os.environ["GITHUB_TOKEN"])).get_repo(f"{ORG}/demo-api")
    try:
        return (
            branch.get_branch("main")
            .get_required_pull_request_reviews()
            .required_approving_review_count
        )
    except Exception:
        return None


# ---------- watching GitHub (presenter's gh login) ----------


def _gh_env() -> dict[str, str]:
    # gh prefers GITHUB_TOKEN over its own login; the demo org token can't read Actions runs.
    return {k: v for k, v in os.environ.items() if k != "GITHUB_TOKEN"}


def gh_json(*args: str) -> Any:
    out = subprocess.run(["gh", *args], env=_gh_env(), capture_output=True, text=True, check=True)
    return json.loads(out.stdout or "null")


def latest_run(repo: str = INFRA) -> dict | None:
    runs = gh_json(
        "run", "list", "--repo", repo, "--limit", "1",
        "--json", "databaseId,status,conclusion,event,url,createdAt",
    )  # fmt: skip
    return runs[0] if runs else None


def run_info(run_id: int, repo: str = INFRA) -> dict:
    return gh_json(
        "run", "view", str(run_id), "--repo", repo, "--json", "status,conclusion,event,url"
    )


@dataclass
class RunUpdate:
    phase: str  # "waiting", "running", "done", "timeout"
    seconds: int
    run: dict | None = None


def follow_new_run(
    before_id: int | None, repo: str = INFRA, start_timeout: int = 120, run_timeout: int = 600
) -> Iterator[RunUpdate]:
    """Yield progress while waiting for a run newer than `before_id` to start and finish."""
    started = time.monotonic()
    run = None
    while time.monotonic() - started < start_timeout:
        latest = latest_run(repo)
        if latest and latest["databaseId"] != before_id:
            run = latest
            break
        yield RunUpdate("waiting", int(time.monotonic() - started))
        time.sleep(3)
    if run is None:
        yield RunUpdate("timeout", int(time.monotonic() - started))
        return
    while time.monotonic() - started < start_timeout + run_timeout:
        info = run_info(run["databaseId"], repo)
        run |= info
        if info["status"] == "completed":
            yield RunUpdate("done", int(time.monotonic() - started), run)
            return
        yield RunUpdate("running", int(time.monotonic() - started), run)
        time.sleep(5)
    yield RunUpdate("timeout", int(time.monotonic() - started), run)


_TIMESTAMP = re.compile(r"^.?\d{4}-\d\d-\d\dT[\d:.]+Z ")


def report_lines(log: str) -> list[str]:
    """DriftPilot's printed result from a run log (between its step header and the step's end)."""
    lines, on, body = [], False, False
    for raw in log.splitlines():
        text = _TIMESTAMP.sub("", raw.split("\t")[-1])
        if text.startswith("##[group]Run driftpilot action"):
            on = True
            continue
        if on and text.startswith("##[endgroup]"):
            body = True
            continue
        if on and text.startswith("##[end-action"):
            break
        if body and text.strip():
            lines.append(text)
    return lines


def run_report(run_id: int, repo: str = INFRA) -> list[str]:
    log = subprocess.run(
        ["gh", "run", "view", str(run_id), "--repo", repo, "--log"],
        env=_gh_env(), capture_output=True, text=True,
    ).stdout  # fmt: skip
    return report_lines(log)


def driftpilot_items(since: datetime, repo: str = INFRA) -> dict[str, list[dict]]:
    """Open DriftPilot issues and PRs created after `since`."""
    fields = "number,title,url,createdAt,body"
    issues = gh_json("issue", "list", "--repo", repo, "--label", "driftpilot", "--json", fields)
    prs = gh_json("pr", "list", "--repo", repo, "--json", fields + ",headRefName")

    def new(items: list[dict]) -> list[dict]:
        return [
            i
            for i in items
            if datetime.fromisoformat(i["createdAt"].replace("Z", "+00:00")) >= since
            and "<!-- driftpilot:key=" in (i.get("body") or "")
        ]

    return {"issues": new(issues), "prs": new(prs)}


def pr_diff(number: int, repo: str = INFRA) -> str:
    return subprocess.run(
        ["gh", "pr", "diff", str(number), "--repo", repo],
        env=_gh_env(), capture_output=True, text=True,
    ).stdout  # fmt: skip


def close_open_demo_items(repo: str = INFRA) -> list[str]:
    """Close every open DriftPilot issue/PR (demo cleanup). Never merges."""
    closed = []
    since = datetime(2000, 1, 1, tzinfo=UTC)
    items = driftpilot_items(since, repo)
    for pr in items["prs"]:
        subprocess.run(
            ["gh", "pr", "close", str(pr["number"]), "--repo", repo, "--delete-branch",
             "--comment", "Closed after the live demo."],
            env=_gh_env(), capture_output=True,
        )  # fmt: skip
        closed.append(f"PR #{pr['number']}")
    for issue in items["issues"]:
        subprocess.run(
            ["gh", "issue", "close", str(issue["number"]), "--repo", repo,
             "--reason", "completed", "--comment", "Fixed during the live demo."],
            env=_gh_env(), capture_output=True,
        )  # fmt: skip
        closed.append(f"issue #{issue['number']}")
    return closed


# ---------- local Docker demo (the DriftPilot engine directly) ----------


def local_scan(use_llm: bool = True):
    from driftpilot.config import load_config
    from driftpilot.scan import run_scan
    from driftpilot.triage.llm import build_llm

    config = load_config(None, DOCKER_DIR)
    llm = build_llm(config.llm) if use_llm else None
    return run_scan(DOCKER_DIR, config, llm=llm)


@dataclass
class Proposal:
    kind: str  # "pull request" or "issue"
    address: str
    action: str
    body: str
    files: dict[str, str]
    verified: bool
    proof: str


class CollectingOutput:
    """A GitHub output stand-in that keeps what DriftPilot would open."""

    def __init__(self) -> None:
        self.proposals: list[Proposal] = []

    def issue(self, item, patch=None) -> str:
        from driftpilot.remediate.github_out import issue_body

        files, verified, proof = (
            (patch.files, patch.verified, patch.proof) if patch else ({}, False, "")
        )
        body = issue_body(item, patch, None)
        self.proposals.append(
            Proposal("issue", item.plan.address, item.plan.action, body, files, verified, proof)
        )
        return "(demo)"

    def pull_request(self, item, patch) -> str:
        from driftpilot.remediate.github_out import pr_body

        self.proposals.append(
            Proposal(
                "pull request", item.plan.address, item.plan.action, pr_body(item, patch, None),
                patch.files, patch.verified, patch.proof,
            )
        )  # fmt: skip
        return "(demo)"


def local_fix(result) -> list[Proposal]:
    from driftpilot.config import load_config
    from driftpilot.remediate.runner import run_remediations
    from driftpilot.triage.llm import build_llm

    config = load_config(None, DOCKER_DIR).model_copy(update={"mode": "open-prs"})
    output = CollectingOutput()
    run_remediations(result, config, build_llm(config.llm), DOCKER_DIR, output)
    return output.proposals


def unified_diff(path: str, new: str) -> str:
    import difflib

    old = (DOCKER_DIR / path).read_text().splitlines()
    return "\n".join(
        difflib.unified_diff(old, new.splitlines(), f"a/{path}", f"b/{path}", lineterm="", n=1)
    )
