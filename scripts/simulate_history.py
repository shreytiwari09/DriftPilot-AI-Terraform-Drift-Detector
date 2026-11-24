"""Generate synthetic drift history with planted patterns (SPEC §7; Phase 3 gate data).

    python scripts/simulate_history.py --out /tmp/history

90 days, one run every 6 hours. Planted, so analytics can be checked against known answers:
  1. a drift-rate spike on SPIKE_DAY (many new drifts in one day),
  2. RECURRING (address, attribute) drifting again every 3 days in the last 14 days,
  3. human overrule rate rising from ~10 % to ~50 % in the last 14 days (plus more severe drift).
Each episode also gets a team, repo, environment, account and drift type (infrastructure or
database), so the dashboard filters have something to show. By default the runs are split into one
stream per repo/environment, like real scans. `simulate(split=False)` keeps the single stream the
Phase 3 gate test was written for; the planted patterns are identical in both.
Seeded: the same seed gives the same history.
"""

import argparse
import hashlib
import random
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from driftpilot.collector import finding_id
from driftpilot.history.store import LocalStore
from driftpilot.models import (
    AuditRecord,
    Context,
    DriftFinding,
    GuardrailEvent,
    HistoryEvent,
    RemediationResult,
    RunRecord,
    Verdict,
)

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
# The last items of some groups are database objects: same number of values and same category as
# the items they stand in for, so the random draws (and the planted patterns) do not change.
DESCRIPTIONS = ["edited by hand", "hotfix note"]
CATALOG = [
    *[(f"github_repository.svc{i}", "description", DESCRIPTIONS, "cosmetic") for i in range(4)],
    ("postgres.public.users", "comment", DESCRIPTIONS, "cosmetic"),
    ("postgres.public.orders", "comment", DESCRIPTIONS, "cosmetic"),
    *[(f"github_repository.svc{i}", "topics", [["demo", "hotfix"], ["demo", "tmp"]], "cosmetic")
      for i in range(4)],
    ("postgres.public.users", "index:idx_users_created", ["renamed", "rebuilt"], "cosmetic"),
    ("postgres.public.orders", "index:idx_orders_status", ["renamed", "rebuilt"], "cosmetic"),
    *[(f"github_repository.svc{i}", "has_issues", [False], "availability") for i in range(2)],
    ("postgres.public.users.email", "nullable", [True], "availability"),
    ("postgres.public.invoices.total", "nullable", [True], "availability"),
    *[(f"github_branch_protection.svc{i}_main",
       "required_pull_request_reviews[0].required_approving_review_count", [0, 1], "security")
      for i in range(2)],
    ("postgres.public.orders", "policy:tenant_isolation", ["dropped", "loosened"], "security"),
    ("postgres.public.payments", "policy:tenant_isolation", ["dropped", "loosened"], "security"),
    *[(f"github_team_repository.team{i}", "permission", ["admin", "maintain"], "security")
      for i in range(3)],
    *[(f"docker_container.app{i}", "memory", [512, 768, 1024], "availability") for i in range(5)],
    *[(f"docker_container.app{i}", "restart", ["on-failure", "no"], "availability")
      for i in range(5)],
]  # fmt: skip
SEVERITY = {"cosmetic": "low", "availability": "medium", "security": "high"}
ACTION = {"cosmetic": "codify", "availability": "codify", "security": "revert"}


@dataclass(frozen=True)
class Stream:
    """One place DriftPilot runs: a repo in one environment. Its runs follow each other."""

    slug: str
    repo: str
    environment: str
    account: str
    drift_type: str
    managed: dict[str, int]  # resources in state, per team
    unmanaged: dict[str, int]


ACCOUNTS = {"prod": "123456789012", "staging": "210987654321", "dev": "345678901234"}
STREAMS = {
    s.slug: s
    for s in [
        Stream("infra-prod", "driftpilot-demo/infra", "prod", ACCOUNTS["prod"], "infrastructure",
               {"payments": 10, "platform": 7, "security": 5}, {"platform": 2}),
        Stream("infra-staging", "driftpilot-demo/infra", "staging", ACCOUNTS["staging"],
               "infrastructure", {"payments": 5, "platform": 4, "security": 3}, {"payments": 1}),
        Stream("platform-prod", "driftpilot-demo/platform", "prod", ACCOUNTS["prod"],
               "infrastructure", {"platform": 8, "growth": 4}, {"growth": 1}),
        Stream("platform-dev", "driftpilot-demo/platform", "dev", ACCOUNTS["dev"],
               "infrastructure", {"platform": 5, "growth": 3}, {}),
        Stream("database-prod", "driftpilot-demo/database", "prod", ACCOUNTS["prod"], "database",
               {"data": 6}, {}),
    ]
}  # fmt: skip
assert sum(sum(s.managed.values()) for s in STREAMS.values()) == MANAGED_RESOURCES


def team_for(address: str) -> str:
    if address.startswith("postgres."):
        return "data"
    if address.startswith(("github_branch_protection", "github_team_repository")):
        return "security"
    if address.startswith("docker_container"):
        return "platform" if int(address[-1]) < 3 else "growth"
    return "payments" if int(address.split(".")[1].removeprefix("svc")) % 2 == 0 else "platform"


def stream_for(address: str) -> Stream:
    """Where this resource lives (decided by the address, so it never uses the random draws)."""
    spread = zlib.crc32(address.encode()) % 3
    if address.startswith("postgres."):
        return STREAMS["database-prod"]
    if address.startswith("docker_container"):
        return STREAMS["platform-dev" if spread == 0 else "platform-prod"]
    return STREAMS["infra-staging" if spread == 0 else "infra-prod"]


def resource_type(address: str, attribute: str) -> str:
    if not address.startswith("postgres."):
        return address.split(".")[0]
    if attribute.startswith("policy:"):
        return "pg_policy"
    if attribute.startswith("index:"):
        return "pg_index"
    return "pg_column" if address.count(".") == 3 else "pg_table"


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
    stream: Stream


def _tags(fid: str, ep: Episode, source: str) -> tuple[list[str], list[str], str]:
    """Compliance tags, guardrail marks and a note for a security finding.

    Chosen from the finding id, not the random draws, so the planted patterns do not change.
    """
    if ep.category != "security":
        return [], [], ""
    controls = (
        ["code-review"]
        if ep.address.startswith("github_branch_protection")
        else ["least-privilege"]
    )
    pick = zlib.crc32(fid.encode()) % 5 if source == "llm" else 99  # only LLM verdicts
    if pick == 0:
        return controls, ["never-soften"], " guardrail: never-soften (branch protection weakened)"
    if pick == 1:
        return controls, ["suspicious-input"], " guardrail: suspicious input (ignore previous)"
    return controls, [], ""


def _verdict(fid: str, ep: Episode, rng: random.Random) -> Verdict:
    source = "rule" if ep.category == "security" and rng.random() < 0.5 else "llm"
    controls, guardrails, note = _tags(fid, ep, source)
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
        reason=f"Simulated: {ep.attribute} on {ep.address} changed by hand.{note}",
        prompt_version="triage-v4" if source == "llm" else None,
        controls=controls,
        guardrails=guardrails,
    )


def simulate(days: int = DAYS, seed: int = 7, end: datetime | None = None, split: bool = False):
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
            stream=stream_for(address),
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
    everything = Stream(  # the single stream of the gate test: all places in one run
        "all", "unknown", "unknown", "unknown", "infrastructure",
        {t: sum(s.managed.get(t, 0) for s in STREAMS.values())
         for s in STREAMS.values() for t in s.managed}, {},
    )  # fmt: skip
    for run in range(n_runs):
        ts = start + timedelta(hours=6 * run, minutes=17 + rng.randrange(5))
        active = [e for e in episodes if e.start_run <= run < e.start_run + e.length]
        groups = (
            [(s, [e for e in active if e.stream is s]) for s in STREAMS.values()]
            if split
            else [(everything, active)]
        )
        for stream, members in groups:
            run_id = f"sim-{run:04d}-{stream.slug}" if split else f"sim-{run:04d}"
            for ep in members:
                events.append(_event(ep, run_id, ts, rng))
            managed = sum(stream.managed.values())
            runs.append(
                RunRecord(
                    run_id=run_id,
                    timestamp=ts,
                    working_dir="simulated",
                    finding_count=len(members),
                    critical_count=sum(e.severity == "critical" for e in members),
                    distinct_resources=len({e.address for e in members}),
                    unmanaged_count=sum(stream.unmanaged.values()),
                    noise_count=rng.randrange(3),
                    managed_resource_count=managed if split else MANAGED_RESOURCES,
                    repo=stream.repo,
                    environment=stream.environment,
                    drift_type=stream.drift_type,
                    managed_by_team=stream.managed,
                    unmanaged_by_team=stream.unmanaged,
                )
            )
    return events, runs


def _event(ep: Episode, run_id: str, ts: datetime, rng: random.Random) -> HistoryEvent:
    fid = finding_id(ep.address, ep.attribute)
    finding = DriftFinding(
        id=fid,
        run_id=run_id,
        detected_at=ts,
        provider="postgres" if ep.stream.drift_type == "database" else "simulated",
        resource_type=resource_type(ep.address, ep.attribute),
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
    return HistoryEvent(
        run_id=run_id,
        timestamp=ts,
        finding=finding,
        verdict=_verdict(fid, ep, rng),
        remediation=remediation,
        human_outcome="overruled" if ep.overruled else "accepted",
        context=Context(
            team=team_for(ep.address),
            repo=ep.stream.repo,
            environment=ep.stream.environment,
            account=ep.stream.account,
            drift_type=ep.stream.drift_type,
        ),
    )


def simulate_audit(events: list[HistoryEvent], runs: list[RunRecord]) -> list[AuditRecord]:
    """One LLM call per 10 findings the model judged (at least one) in each run, with the
    guardrail events of findings that appear for the first time. Hashes only, like the real log."""
    by_run: dict[str, list[HistoryEvent]] = {}
    for e in events:
        by_run.setdefault(e.run_id, []).append(e)
    previous: dict[tuple, set[str]] = {}
    audit = []
    for r in sorted(runs, key=lambda r: r.timestamp):
        here = by_run.get(r.run_id, [])
        key = (r.repo, r.environment, r.drift_type)
        new = [e for e in here if e.finding.id not in previous.get(key, set())]
        previous[key] = {e.finding.id for e in here}
        judged = [e for e in new if e.verdict.source == "llm"]
        for i in range(-(-len(judged) // 10)):  # ceil
            batch = judged[i * 10 : (i + 1) * 10]
            events_ = [
                GuardrailEvent(
                    kind=g,
                    finding_id=e.finding.id,
                    detail=e.verdict.reason.split("guardrail: ")[-1],
                )
                for e in batch
                for g in e.verdict.guardrails
            ]
            digest = hashlib.sha256(f"{r.run_id}-{i}".encode()).hexdigest()
            audit.append(
                AuditRecord(
                    run_id=r.run_id,
                    timestamp=r.timestamp,
                    purpose="triage",
                    prompt_version="triage-v4",
                    model="simulated",
                    prompt_sha256=digest,
                    response_sha256=digest[::-1],
                    valid=zlib.crc32(digest.encode()) % 40 != 0,
                    finding_ids=[e.finding.id for e in batch],
                    guardrail_events=events_,
                )
            )
    return audit


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
    parser.add_argument(
        "--single-stream", action="store_true", help="one run stream, as the Phase 3 gate uses"
    )
    args = parser.parse_args(argv)
    events, runs = simulate(args.days, args.seed, split=not args.single_stream)
    store = LocalStore(args.out)
    store.save(events, runs, "simulated")
    store.append_audit(simulate_audit(events, runs), "simulated")
    print(f"wrote {len(events)} events, {len(runs)} runs to {args.out}")
    print(
        f"planted: spike on day {SPIKE_DAY}, recurring {RECURRING}, "
        f"overrule rise in the last {RECENT_DAYS} days"
    )


if __name__ == "__main__":
    main()
