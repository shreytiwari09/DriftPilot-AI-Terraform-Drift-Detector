"""Run DriftPilot configurations over the labelled cases and score them (SPEC §8)."""

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from driftpilot.collector import parse_plan, resource_values
from driftpilot.config import Config
from driftpilot.evaluation.dataset import EVAL_TIME, Case, Expected
from driftpilot.models import DriftFinding, Verdict
from driftpilot.triage.llm import LLMClient
from driftpilot.triage.llm_triage import triage_findings
from driftpilot.triage.policy import apply_policy
from driftpilot.triage.rules import apply_rules, load_rules


@dataclass(frozen=True)
class Setup:
    name: str
    rules: bool
    llm: str | None  # None, "cloud" or "local"
    raw: bool = False  # plain Terraform: every diff is "real", no judgment, blind to unmanaged


SETUPS = [
    Setup("raw terraform", rules=False, llm=None, raw=True),
    Setup("rules only", rules=True, llm=None),
    Setup("rules + local LLM", rules=True, llm="local"),
    Setup("rules + cloud LLM", rules=True, llm="cloud"),
    Setup("cloud LLM without rules", rules=False, llm="cloud"),
]


class Item(BaseModel):
    """One labelled finding and what a setup predicted for it."""

    case_id: str
    address: str | None
    attribute: str | None
    label_real: bool
    label_severity: str
    label_actions: list[str]
    pred_real: bool
    pred_severity: str | None
    pred_action: str | None
    source: str | None  # rule / llm / policy / None


class CachingLLM:
    """Wraps an LLM client; answers are stored on disk by prompt hash so re-runs cost nothing.

    `salt` separates repeated runs (prompt stability) that must not reuse each other's answers.
    """

    def __init__(self, inner: LLMClient, cache_dir: Path, salt: str = "") -> None:
        self.inner = inner
        self.provider, self.model = inner.provider, inner.model
        self.dir = cache_dir
        self.salt = salt
        self.calls = 0  # real (uncached) calls
        self.hits = 0

    def complete_json(self, system: str, prompt: str, schema: dict[str, Any]) -> str:
        key = hashlib.sha256(
            json.dumps([self.model, self.salt, system, prompt, schema], sort_keys=True).encode()
        ).hexdigest()[:24]
        path = self.dir / f"{key}.json"
        if path.exists():
            self.hits += 1
            return json.loads(path.read_text())["answer"]
        answer = self.inner.complete_json(system, prompt, schema)
        self.calls += 1
        self.dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"model": self.model, "salt": self.salt, "answer": answer}))
        return answer


def _label_for(expect: list[Expected], f: DriftFinding, single_resource: bool) -> Expected | None:
    for e in expect:
        same_attr = e.attribute == f.attribute_path
        same_addr = e.address == f.address or (e.address is None and single_resource)
        if same_attr and same_addr:
            return e
    return None


NOISE = Expected(real=False, severity="none", action=["none"])


def run_case(
    case: Case, setup: Setup, llm: LLMClient | None, root: Path, fixtures: Path
) -> list[Item]:
    plan = case.plan(fixtures)
    findings = parse_plan(plan, case.id, EVAL_TIME) if plan else []
    unmanaged = [u] if (u := case.unmanaged_finding()) else []

    verdicts: dict[str, Verdict] = {}
    if not setup.raw:
        if setup.rules and plan:
            verdicts = apply_rules(findings, load_rules(), resource_values(plan))
        if llm is not None and findings:
            verdicts |= triage_findings(llm, findings, verdicts, case.code_path(root))
        verdicts = apply_policy(findings, unmanaged, verdicts, Config())

    items: list[Item] = []
    single = len({f.address for f in findings}) <= 1
    matched: set[int] = set()
    for f in findings:
        label = _label_for(case.expect, f, single)
        if label is not None:
            matched.add(id(label))
        elif case.default == "noise":
            label = NOISE
        else:
            raise ValueError(f"case {case.id}: no label for {f.address} {f.attribute_path!r}")
        v = verdicts.get(f.id)
        items.append(
            Item(
                case_id=case.id,
                address=f.address,
                attribute=f.attribute_path,
                label_real=label.real,
                label_severity=label.severity,
                label_actions=label.action,
                pred_real=True if v is None else v.is_real_drift,
                pred_severity=None if v is None else v.severity,
                pred_action=None if v is None else v.recommended_action,
                source=None if v is None else v.source,
            )
        )
    for u in unmanaged:
        label = case.expect[0]
        matched.add(id(label))
        v = None if setup.raw else verdicts.get(u.id)
        items.append(
            Item(
                case_id=case.id,
                address=f"{u.resource_kind}:{u.name}",
                attribute=None,
                label_real=label.real,
                label_severity=label.severity,
                label_actions=label.action,
                pred_real=v is not None,  # raw Terraform never sees unmanaged resources
                pred_severity=None if v is None else v.severity,
                pred_action=None if v is None else v.recommended_action,
                source=None if v is None else v.source,
            )
        )
    missing = [e for e in case.expect if id(e) not in matched]
    if missing:
        raise ValueError(f"case {case.id}: expected findings not produced: {missing}")
    return items


@dataclass
class SetupResult:
    setup: Setup
    items: list[Item] = field(default_factory=list)
    llm_calls: int = 0
    cache_hits: int = 0
    seconds: float = 0.0
    prompt_chars: int = 0
    skipped: str | None = None

    def metrics(self) -> dict[str, float | None]:
        real = [i for i in self.items if i.label_real]
        noise = [i for i in self.items if not i.label_real]
        critical = [i for i in real if i.label_severity == "critical"]

        def share(hits: int, total: int) -> float | None:
            return round(hits / total, 3) if total else None

        return {
            "noise_reduction": share(sum(not i.pred_real for i in noise), len(noise)),
            "real_drift_recall": share(sum(i.pred_real for i in real), len(real)),
            "severity_accuracy": share(
                sum(i.pred_severity == i.label_severity for i in real), len(real)
            ),
            "critical_recall": share(
                sum(i.pred_severity == "critical" for i in critical), len(critical)
            ),
            "action_accuracy": share(
                sum(i.pred_action in i.label_actions for i in real), len(real)
            ),
            "false_alarm_rate": share(sum(i.pred_real for i in noise), len(noise)),
        }


class CountingLLM:
    """Counts prompt characters (a rough token proxy: ~4 characters per token)."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.provider, self.model = inner.provider, inner.model
        self.chars = 0

    def complete_json(self, system: str, prompt: str, schema: dict[str, Any]) -> str:
        self.chars += len(system) + len(prompt)
        return self.inner.complete_json(system, prompt, schema)


def run_setup(
    cases: list[Case],
    setup: Setup,
    llm: CachingLLM | None,
    root: Path,
    fixtures: Path,
) -> SetupResult:
    result = SetupResult(setup)
    if setup.llm is not None and llm is None:
        result.skipped = "no LLM configured for this setup"
        return result
    counter = CountingLLM(llm) if llm is not None else None
    start_calls, start_hits = (llm.calls, llm.hits) if llm else (0, 0)
    start = time.perf_counter()
    for case in cases:
        result.items += run_case(case, setup, counter, root, fixtures)
    result.seconds = round(time.perf_counter() - start, 1)
    if llm is not None:
        result.llm_calls = llm.calls - start_calls
        result.cache_hits = llm.hits - start_hits
        result.prompt_chars = counter.chars
    return result


def prompt_stability(
    cases: list[Case],
    make_llm: Any,
    root: Path,
    fixtures: Path,
    repeats: int = 5,
    max_cases: int = 12,
) -> dict[str, Any]:
    """Run rules + cloud LLM `repeats` times; share of LLM-judged findings judged identically."""
    setup = next(s for s in SETUPS if s.name == "rules + cloud LLM")
    rules = load_rules()
    chosen = []
    for case in cases:
        plan = case.plan(fixtures)
        if not plan:
            continue
        findings = parse_plan(plan, case.id, EVAL_TIME)
        if any(f.id not in apply_rules(findings, rules, resource_values(plan)) for f in findings):
            chosen.append(case)
        if len(chosen) == max_cases:
            break
    runs: list[dict[tuple, tuple]] = []
    calls = 0
    for r in range(repeats):
        llm = make_llm(f"repeat-{r}")
        answers = {}
        for case in chosen:
            for i in run_case(case, setup, llm, root, fixtures):
                if i.source in ("llm", "policy"):  # judged by the LLM (policy may adjust it)
                    answers[(i.case_id, i.address, i.attribute)] = (i.pred_severity, i.pred_action)
        calls += llm.calls
        runs.append(answers)
    keys = set().union(*runs) if runs else set()
    stable = sum(len({run.get(k) for run in runs}) == 1 for k in keys)
    return {
        "repeats": repeats,
        "cases": len(chosen),
        "findings": len(keys),
        "identical_share": round(stable / len(keys), 3) if keys else None,
        "llm_calls": calls,
    }
