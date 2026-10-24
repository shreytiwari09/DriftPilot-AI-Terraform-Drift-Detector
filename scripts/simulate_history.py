"""Generate synthetic drift history with planted patterns (SPEC §7; Phase 3 gate data).

    python scripts/simulate_history.py --out /tmp/history

90 days, one run every 6 hours. Planted, so analytics can be checked against known answers:
  1. a drift-rate spike on SPIKE_DAY (many new drifts in one day),
  2. RECURRING (address, attribute) drifting again every 3 days in the last 14 days,
  3. human overrule rate rising from ~10 % to ~50 % in the last 14 days (plus more severe drift).
Seeded: the same seed gives the same history.
"""

import argparse
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from driftpilot.collector import finding_id
from driftpilot.history.store import LocalStore
from driftpilot.models import DriftFinding, HistoryEvent, RemediationResult, RunRecord, Verdict

DAYS = 90
RUNS_PER_DAY = 4
SPIKE_DAY = 60
SPIKE_EPISODES = 16
RECENT_DAYS = 14
RECURRING = ("docker_container.app3", "memory")
BASE_RATE = 1.5  # new drift episodes per day
OVERRULE_BEFORE, OVERRULE_RECENT = 0.10, 0.50
MANAGED_RESOURCES = 60
REPO = "https://github.com/driftpilot-demo/infra"

# (address, attribute, values to drift to, category)
CATALOG = [
    *[(f"github_repository.svc{i}", "description", ["edited by hand", "hotfix note"], "cosmetic")
      for i in range(6)],
    *[(f"github_repository.svc{i}", "topics", [["demo", "hotfix"], ["demo", "tmp"]], "cosmetic")
      for i in range(6)],
    *[(f"github_repository.svc{i}", "has_issues", [False], "availability") for i in range(4)],
    *[(f"github_branch_protection.svc{i}_main",
       "required_pull_request_reviews[0].required_approving_review_count", [0, 1], "security")
      for i in range(4)],
    *[(f"github_team_repository.team{i}", "permission", ["admin", "maintain"], "security")
      for i in range(3)],
    *[(f"docker_container.app{i}", "memory", [512, 768, 1024], "availability") for i in range(5)],
    *[(f"docker_container.app{i}", "restart", ["on-failure", "no"], "availability")
      for i in range(5)],
]  # fmt: skip
SEVERITY = {"cosmetic": "low", "availability": "medium", "security": "high"}
ACTION = {"cosmetic": "codify", "availability": "codify", "security": "revert"}


@dataclass
class Episode:
    address: str
    attribute: str
    after: object
    category: str
    start_run: int
    length: int  # runs
    overruled: bool
    severity: str


def _verdict(fid: str, ep: Episode, rng: random.Random) -> Verdict:
    source = "rule" if ep.category == "security" and rng.random() < 0.5 else "llm"
    return Verdict(
        finding_id=fid,
        source=source,
        rule_id="simulated" if source == "rule" else None,
        is_real_drift=True,
        severity=ep.severity,
        category=ep.category,
        intent="likely_hotfix" if ep.category != "security" else "likely_accidental",
        recommended_action=ACTION[ep.category],
        confidence=round(rng.uniform(0.75, 0.95), 2),
        reason=f"Simulated: {ep.attribute} on {ep.address} changed by hand.",
        prompt_version="triage-v2" if source == "llm" else None,
    )


def simulate(days: int = DAYS, seed: int = 7, end: datetime | None = None):
    rng = random.Random(seed)
    end = end or datetime(2026, 10, 25, tzinfo=UTC)
    start = end - timedelta(days=days)
    n_runs = days * RUNS_PER_DAY
    recent_from = (days - RECENT_DAYS) * RUNS_PER_DAY

    def new_episode(run: int, item=None) -> Episode:
        address, attribute, values, category = item or rng.choice(CATALOG)
        recent = run >= recent_from
        severity = SEVERITY[category]
        if recent and rng.random() < 0.4:  # severity mix shifts upward lately
            severity = "critical" if category == "security" else "high"
        return Episode(
            address=address,
            attribute=attribute,
            after=rng.choice(values),
            category=category,
            start_run=run,
            length=rng.randint(1, 8),
            overruled=rng.random() < (OVERRULE_RECENT if recent else OVERRULE_BEFORE),
            severity=severity,
        )

    episodes: list[Episode] = []
    for day in range(days):
        count = SPIKE_EPISODES if day == SPIKE_DAY else _poisson(rng, BASE_RATE)
        for _ in range(count):
            episodes.append(new_episode(day * RUNS_PER_DAY + rng.randrange(RUNS_PER_DAY)))
    recurring_item = next(c for c in CATALOG if (c[0], c[1]) == RECURRING)
    for day in range(days - RECENT_DAYS + 1, days, 3):
        ep = new_episode(day * RUNS_PER_DAY, recurring_item)
        ep.length = 2  # fixed quickly, then back again
        episodes.append(ep)

    events: list[HistoryEvent] = []
    runs: list[RunRecord] = []
    for run in range(n_runs):
        ts = start + timedelta(hours=6 * run, minutes=17 + rng.randrange(5))
        run_id = f"sim-{run:04d}"
        active = [e for e in episodes if e.start_run <= run < e.start_run + e.length]
        for ep in active:
            fid = finding_id(ep.address, ep.attribute)
            finding = DriftFinding(
                id=fid,
                run_id=run_id,
                detected_at=ts,
                provider="simulated",
                resource_type=ep.address.split(".")[0],
                address=ep.address,
                change_kind="modified",
                attribute_path=ep.attribute,
                before="as in code",
                after=ep.after,
            )
            kind = "pull" if ACTION[ep.category] == "codify" else "issues"
            remediation = RemediationResult(
                finding_id=fid,
                action=ACTION[ep.category],
                verified=kind == "pull",
                attempts=1,
                pr_url=f"{REPO}/pull/{ep.start_run}" if kind == "pull" else None,
                issue_url=f"{REPO}/issues/{ep.start_run}" if kind == "issues" else None,
                finding_ids=[fid],
            )
            outcome = "overruled" if ep.overruled else "accepted"
            events.append(
                HistoryEvent(
                    run_id=run_id,
                    timestamp=ts,
                    finding=finding,
                    verdict=_verdict(fid, ep, rng),
                    remediation=remediation,
                    human_outcome=outcome,
                )
            )
        runs.append(
            RunRecord(
                run_id=run_id,
                timestamp=ts,
                working_dir="simulated",
                finding_count=len(active),
                critical_count=sum(e.severity == "critical" for e in active),
                distinct_resources=len({e.address for e in active}),
                unmanaged_count=0,
                noise_count=rng.randrange(3),
                managed_resource_count=MANAGED_RESOURCES,
            )
        )
    return events, runs


def _poisson(rng: random.Random, lam: float) -> int:
    """Knuth's method; avoids a numpy dependency for one draw."""
    limit, k, p = 2.718281828459045**-lam, 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--out", type=Path, required=True, help="history folder to write")
    parser.add_argument("--days", type=int, default=DAYS)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)
    events, runs = simulate(args.days, args.seed)
    LocalStore(args.out).save(events, runs, "simulated")
    print(f"wrote {len(events)} events, {len(runs)} runs to {args.out}")
    print(
        f"planted: spike on day {SPIKE_DAY}, recurring {RECURRING}, "
        f"overrule rise in the last {RECENT_DAYS} days"
    )


if __name__ == "__main__":
    main()
