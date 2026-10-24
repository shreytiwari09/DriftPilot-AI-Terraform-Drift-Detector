"""Evaluate the YAML rule pack against findings (SPEC §4.4 step 1)."""

import json
import re
from collections.abc import Callable
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel

from driftpilot.models import Action, Category, DriftFinding, Intent, Severity, Verdict

ADMIN_PORTS = (22, 3389)
OPEN_CIDRS = {"0.0.0.0/0", "::/0"}


class RuleMatch(BaseModel):
    type: str = "*"
    attribute: str = "*"
    change_kind: Literal["modified", "deleted"] | None = None


class RuleVerdict(BaseModel):
    is_real_drift: bool
    severity: Severity
    category: Category
    intent: Intent
    recommended_action: Action
    confidence: float
    reason: str


class Rule(BaseModel):
    id: str
    description: str = ""
    match: RuleMatch = RuleMatch()
    when: str | dict[str, Any] | None = None
    verdict: RuleVerdict


@cache
def _glob(pattern: str) -> re.Pattern[str]:
    """`*` matches anything; everything else is literal (attribute paths contain `[0]`)."""
    return re.compile(".*".join(re.escape(part) for part in pattern.split("*")) + r"\Z")


def glob_match(pattern: str, text: str) -> bool:
    return bool(_glob(pattern).match(text))


def _is_zero_value(value: Any) -> bool:
    """Empty/zero defaults a provider fills in: [], {}, "", 0, False."""
    return value is not None and not value and isinstance(value, list | dict | str | int | float)


def _null_to_default(f: DriftFinding, _: Any, __: Any) -> bool:
    return (f.before is None and _is_zero_value(f.after)) or (
        _is_zero_value(f.before) and f.after is None
    )


def _list_reordered(f: DriftFinding, _: Any, __: Any) -> bool:
    if not (isinstance(f.before, list) and isinstance(f.after, list)) or f.before == f.after:
        return False
    key = lambda items: sorted(json.dumps(i, sort_keys=True) for i in items)  # noqa: E731
    return key(f.before) == key(f.after)


def _json_equal(f: DriftFinding, _: Any, __: Any) -> bool:
    if not (isinstance(f.before, str) and isinstance(f.after, str)) or f.before == f.after:
        return False
    try:
        return json.loads(f.before) == json.loads(f.after)
    except ValueError:
        return False


def _decreased(f: DriftFinding, _: Any, __: Any) -> bool:
    numbers = (int, float)
    return (
        isinstance(f.before, numbers)
        and isinstance(f.after, numbers)
        and not isinstance(f.before, bool)
        and f.after < f.before
    )


def _changed_to(f: DriftFinding, value: Any, _: Any) -> bool:
    return f.after == value and f.before != value


def _has_open_admin_port(block: Any) -> bool:
    """Does an ingress-style dict allow 0.0.0.0/0 (or ::/0) to port 22 or 3389?"""
    if not isinstance(block, dict):
        return False
    cidrs = set(block.get("cidr_blocks") or []) | set(block.get("ipv6_cidr_blocks") or [])
    cidrs |= {block.get("cidr_ipv4"), block.get("cidr_ipv6")}
    if not cidrs & OPEN_CIDRS:
        return False
    from_port, to_port = block.get("from_port"), block.get("to_port")
    if from_port is None or to_port is None:
        return False
    if from_port == 0 and to_port == 0 and block.get("protocol") in ("-1", "all"):
        return True  # all traffic
    return any(from_port <= port <= to_port for port in ADMIN_PORTS)


def _open_cidr_on_admin_port(f: DriftFinding, _: Any, resource: Any) -> bool:
    """Looks at the whole drifted resource, since port and CIDR are separate attributes."""
    if not isinstance(resource, dict):
        return False
    if _has_open_admin_port(resource):  # standalone rule resources
        return True
    root = (f.attribute_path or "").split("[")[0].split(".")[0]
    blocks = resource.get(root) if root in ("ingress",) else None
    return any(_has_open_admin_port(b) for b in blocks or [])


Predicate = Callable[[DriftFinding, Any, Any], bool]
PREDICATES: dict[str, Predicate] = {
    "null_to_default": _null_to_default,
    "list_reordered": _list_reordered,
    "json_equal": _json_equal,
    "decreased": _decreased,
    "changed_to": _changed_to,
    "open_cidr_on_admin_port": _open_cidr_on_admin_port,
}


def _predicate(when: str | dict[str, Any] | None) -> tuple[Predicate | None, Any]:
    if when is None:
        return None, None
    if isinstance(when, str):
        name, arg = when, None
    else:
        [(name, arg)] = when.items()
    if name not in PREDICATES:
        raise ValueError(f"unknown rule predicate: {name}")
    return PREDICATES[name], arg


def load_rules(path: Path | None = None) -> list[Rule]:
    if path is None:
        text = resources.files("driftpilot.triage").joinpath("rules/default.yaml").read_text()
    else:
        text = path.read_text()
    rules = [Rule.model_validate(r) for r in yaml.safe_load(text)["rules"]]
    for rule in rules:
        _predicate(rule.when)  # fail fast on typos
    return rules


def rule_matches(rule: Rule, finding: DriftFinding, resource: Any = None) -> bool:
    m = rule.match
    if m.change_kind and finding.change_kind != m.change_kind:
        return False
    if not _glob(m.type).match(finding.resource_type):
        return False
    if m.attribute != "*" and not _glob(m.attribute).match(finding.attribute_path or ""):
        return False
    predicate, arg = _predicate(rule.when)
    return predicate is None or predicate(finding, arg, resource)


def apply_rules(
    findings: list[DriftFinding],
    rules: list[Rule],
    resources_by_address: dict[str, Any] | None = None,
) -> dict[str, Verdict]:
    """Verdict for each finding a rule decides (first match wins). Others are left out."""
    resources_by_address = resources_by_address or {}
    verdicts: dict[str, Verdict] = {}
    for finding in findings:
        resource = resources_by_address.get(finding.address)
        for rule in rules:
            if rule_matches(rule, finding, resource):
                verdicts[finding.id] = Verdict(
                    finding_id=finding.id,
                    source="rule",
                    rule_id=rule.id,
                    **rule.verdict.model_dump(),
                )
                break
    return verdicts
