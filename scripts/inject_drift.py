"""Inject and revert the 14 drift scenarios from SPEC §7 (demo and eval helper, not DriftPilot).

    python scripts/inject_drift.py list
    python scripts/inject_drift.py inject 2 3 5
    python scripts/inject_drift.py revert 2 3 5 --tf-dir ../driftpilot-infra/infra

GitHub scenarios need GITHUB_TOKEN (the demo org's fine-grained PAT). Revert values match the
Terraform code in demo/github and demo/docker; keep them in sync if that code changes.
Scenarios 1 and 10 delete a resource, so reverting them means `terraform apply` (needs --tf-dir).
"""

import argparse
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

ORG = "driftpilot-demo"
API_REPO, WEB_REPO, HANDMADE_REPO = "demo-api", "demo-web", "demo-handmade"
TEAM = "developers"
API_DESCRIPTION = "DriftPilot demo service (managed by Terraform)"
TOPICS = ["driftpilot", "demo"]
REQUIRED_APPROVALS = 2
HOTFIX_CHECK = "ci/hotfix-check"

WEB_CONTAINER, CACHE_CONTAINER, HANDMADE_CONTAINER = (
    "driftpilot-demo-web",
    "driftpilot-demo-cache",
    "driftpilot-handmade",
)
MANAGED_LABELS = {"managed-by": "terraform", "app": "driftpilot-demo"}


@dataclass
class Scenario:
    number: int
    provider: str
    description: str
    expected: str
    inject: Callable[[argparse.Namespace], None]
    revert: Callable[[argparse.Namespace], None]


# ---------- clients ----------


@cache
def github() -> Any:
    from github import Auth, Github

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("GITHUB_TOKEN is not set")
    return Github(auth=Auth.Token(token))


def repo(name: str) -> Any:
    return github().get_repo(f"{ORG}/{name}")


def main_branch() -> Any:
    return repo(API_REPO).get_branch("main")


@cache
def docker_client() -> Any:
    import docker

    return docker.from_env()


def container(name: str) -> Any:
    return docker_client().containers.get(name)


def terraform_apply(args: argparse.Namespace, why: str) -> None:
    """Recreate deleted resources from code, then accept the provider's first-refresh defaults."""
    if not args.tf_dir:
        print(
            f"  {why}: run `terraform apply` (then `terraform apply -refresh-only`) in the demo dir"
        )
        return
    for cmd in (["apply", "-auto-approve"], ["apply", "-refresh-only", "-auto-approve"]):
        subprocess.run(
            ["terraform", *cmd, "-input=false", "-no-color"], cwd=args.tf_dir, check=True
        )


def noop(_: argparse.Namespace) -> None:
    pass


# ---------- GitHub scenarios ----------


def s1_inject(_: argparse.Namespace) -> None:
    main_branch().remove_protection()


def s1_revert(args: argparse.Namespace) -> None:
    # A rule recreated through the API gets a new ID that state doesn't know, so use Terraform.
    terraform_apply(args, "recreate branch protection")


def set_approvals(count: int) -> None:
    main_branch().edit_required_pull_request_reviews(required_approving_review_count=count)


def set_team_permission(permission: str) -> None:
    team = github().get_organization(ORG).get_team_by_slug(TEAM)
    team.update_team_repository(repo(API_REPO), permission)


def s5_inject(_: argparse.Namespace) -> None:
    # Status checks aren't enabled on the rule yet, so the PATCH endpoint would 404;
    # re-PUT the whole rule with the same approvals plus one check (an "incident" check).
    main_branch().edit_protection(
        strict=False, contexts=[HOTFIX_CHECK], required_approving_review_count=REQUIRED_APPROVALS
    )


def s5_revert(_: argparse.Namespace) -> None:
    main_branch().remove_required_status_checks()


def s9_inject(_: argparse.Namespace) -> None:
    github().get_organization(ORG).create_repo(
        HANDMADE_REPO, description="Created by hand outside Terraform", private=False
    )


def s9_revert(_: argparse.Namespace) -> None:
    repo(HANDMADE_REPO).delete()


# ---------- Docker scenarios ----------


def s10_inject(_: argparse.Namespace) -> None:
    container(CACHE_CONTAINER).remove(force=True)


def s10_revert(args: argparse.Namespace) -> None:
    terraform_apply(args, "recreate the cache container")


def set_memory(mem: str, swap: str) -> None:
    container(WEB_CONTAINER).update(mem_limit=mem, memswap_limit=swap)


def set_restart(policy: dict[str, Any]) -> None:
    container(WEB_CONTAINER).update(restart_policy=policy)


def s13_inject(_: argparse.Namespace) -> None:
    docker_client().containers.run(
        "nginx:alpine", name=HANDMADE_CONTAINER, labels=MANAGED_LABELS, detach=True
    )


def s13_revert(_: argparse.Namespace) -> None:
    container(HANDMADE_CONTAINER).remove(force=True)


SCENARIOS = {
    s.number: s
    for s in [
        Scenario(1, "github", "Branch protection on demo-api main deleted", "critical / revert",
                 s1_inject, s1_revert),
        Scenario(2, "github", "Required approvals 2 -> 0", "critical / revert",
                 lambda _: set_approvals(0), lambda _: set_approvals(REQUIRED_APPROVALS)),
        Scenario(3, "github", "Team developers access pull -> admin", "high / revert",
                 lambda _: set_team_permission("admin"), lambda _: set_team_permission("pull")),
        Scenario(4, "github", "demo-web archived", "high / investigate",
                 lambda _: repo(WEB_REPO).edit(archived=True),
                 lambda _: repo(WEB_REPO).edit(archived=False)),
        Scenario(5, "github", f"Required status check '{HOTFIX_CHECK}' added", "medium / codify",
                 s5_inject, s5_revert),
        Scenario(6, "github", "has_issues turned off on demo-api", "medium / codify or revert",
                 lambda _: repo(API_REPO).edit(has_issues=False),
                 lambda _: repo(API_REPO).edit(has_issues=True)),
        Scenario(7, "github", "demo-api description edited", "low / codify",
                 lambda _: repo(API_REPO).edit(description="Hotfix: edited by hand"),
                 lambda _: repo(API_REPO).edit(description=API_DESCRIPTION)),
        Scenario(8, "github", "demo-api topics changed", "low / codify",
                 lambda _: repo(API_REPO).replace_topics([*TOPICS, "hotfix"]),
                 lambda _: repo(API_REPO).replace_topics(TOPICS)),
        Scenario(9, "github", f"New repo {HANDMADE_REPO} created by hand", "unmanaged / import",
                 s9_inject, s9_revert),
        Scenario(10, "docker", "Cache container removed (docker rm -f)", "high / recreate",
                 s10_inject, s10_revert),
        Scenario(11, "docker", "Web memory 256m -> 512m", "medium / codify or revert",
                 lambda _: set_memory("512m", "1g"), lambda _: set_memory("256m", "512m")),
        Scenario(12, "docker", "Web restart policy -> on-failure:3", "medium / codify",
                 lambda _: set_restart({"Name": "on-failure", "MaximumRetryCount": 3}),
                 lambda _: set_restart({"Name": "unless-stopped", "MaximumRetryCount": 0})),
        Scenario(13, "docker", "Labelled container started by hand", "unmanaged / import",
                 s13_inject, s13_revert),
        Scenario(14, "both", "No change (control)", "nothing reported", noop, noop),
    ]
}  # fmt: skip


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("command", choices=["list", "inject", "revert"])
    parser.add_argument("scenarios", nargs="*", type=int, help="scenario numbers (1-14)")
    parser.add_argument("--tf-dir", type=Path, help="Terraform dir for reverts that need apply")
    args = parser.parse_args(argv)

    if args.command == "list":
        for s in SCENARIOS.values():
            print(f"{s.number:>2}  {s.provider:<6}  {s.description:<48}  expected: {s.expected}")
        return
    unknown = [n for n in args.scenarios if n not in SCENARIOS]
    if not args.scenarios or unknown:
        parser.error(f"give scenario numbers 1-14 (unknown: {unknown})")
    for number in args.scenarios:
        scenario = SCENARIOS[number]
        print(f"{args.command} {number}: {scenario.description}")
        getattr(scenario, args.command)(args)


if __name__ == "__main__":
    main()
