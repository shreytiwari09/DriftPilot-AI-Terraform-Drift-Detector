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

from driftpilot.models import (
    SEVERITY_RANK,
    Action,
    Category,
    DriftFinding,
    Intent,
    Severity,
    Verdict,
)

# Descriptive tags, not CIS/SOC 2 control numbers (those must be checked against the primary texts).
CONTROL_TAGS = frozenset(
    {
        "public-storage",
        "network-exposure",
        "least-privilege",
        "encryption-at-rest",
        "audit-logging",
        "code-review",
        "backup",
        "data-integrity",  # database constraints and NOT NULL
        "pii",  # personal data
    }
)
ADMIN_PORTS = (22, 3389)
OPEN_CIDRS = {"0.0.0.0/0", "::/0"}


class RuleMatch(BaseModel):
    type: str = "*"
    attribute: str = "*"
    change_kind: Literal["modified", "deleted", "added"] | None = None


class RuleVerdict(BaseModel):
    is_real_drift: bool
    severity: Severity
    category: Category
    intent: Intent
    recommended_action: Action
    confidence: float
    reason: str


class NeverSoften(BaseModel):
    """A security weakening that an LLM verdict may not play down (`never_soften:` in the pack)."""

    type: str = "*"
    attribute: str = "*"
    change_kind: Literal["modified", "deleted", "added"] | None = None
    when: str | dict[str, Any] | None = None
    floor_severity: Severity
    reason: str
    controls: list[str] = []


class Rule(BaseModel):
    id: str
    description: str = ""
    match: RuleMatch = RuleMatch()
    when: str | dict[str, Any] | None = None
    controls: list[str] = []  # descriptive compliance tags shown in the issue and the summary
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


def _policy_statements(document: Any) -> list[dict]:
    """The statements of an IAM-style JSON policy (a JSON string or an already parsed dict)."""
    try:
        doc = json.loads(document) if isinstance(document, str) else document
    except ValueError:
        return []
    if not isinstance(doc, dict):
        return []
    statements = doc.get("Statement", [])
    statements = [statements] if isinstance(statements, dict) else statements
    return [s for s in statements if isinstance(s, dict) and s.get("Effect", "Allow") == "Allow"]


def _has_star(value: Any) -> bool:
    return value == "*" or (isinstance(value, list) and "*" in value)


def _wildcard_principal(document: Any) -> bool:
    for statement in _policy_statements(document):
        principal = statement.get("Principal")
        if _has_star(principal) or (
            isinstance(principal, dict) and _has_star(principal.get("AWS"))
        ):
            return True
    return False


def _any_wildcard(document: Any) -> bool:
    return any(
        _has_star(s.get("Action")) or _has_star(s.get("Resource"))
        for s in _policy_statements(document)
    )


def _json_wildcard_principal(f: DriftFinding, _: Any, __: Any) -> bool:
    """The policy now lets anyone (`Principal: "*"`) in, and did not before."""
    return _wildcard_principal(f.after) and not _wildcard_principal(f.before)


def _iam_wildcard(f: DriftFinding, _: Any, __: Any) -> bool:
    """The policy now allows `Action: "*"` or `Resource: "*"`, and did not before."""
    return _any_wildcard(f.after) and not _any_wildcard(f.before)


def _tags_all_mirrors_tags(f: DriftFinding, _: Any, resource: Any) -> bool:
    """`tags_all.K` changed the same way as `tags.K`: the provider copies tags into tags_all.

    A key that is only in `tags_all` comes from the provider's `default_tags`; that stays real.
    """
    path = f.attribute_path or ""
    if not path.startswith("tags_all.") or not isinstance(resource, dict):
        return False
    tags = resource.get("tags")
    key = path.removeprefix("tags_all.")
    return isinstance(tags, dict) and key in tags and tags[key] == f.after


_PII_SUBSTRINGS = ("email", "phone", "passport", "aadhaar", "aadhar", "birth", "mobile")
_PII_TOKENS = {"ssn", "dob", "pan", "card", "iban", "sin", "nin", "tin"}
_NAME_PARTS = re.compile(r"[^A-Za-z0-9]+|(?<=[a-z0-9])(?=[A-Z])")


def _pii_name(f: DriftFinding, _: Any, __: Any) -> bool:
    """A new database column whose name suggests personal data (email, phone, ssn, card ...)."""
    if f.resource_type != "pg_column":
        return False
    name = f.address.rsplit(".", 1)[-1]
    tokens = {t.lower() for t in _NAME_PARTS.split(name) if t}
    return bool(tokens & _PII_TOKENS) or any(w in name.lower() for w in _PII_SUBSTRINGS)


def _always_true(expression: Any) -> bool:
    text = "".join(str(expression or "").lower().split()).strip("()")
    return text in ("true", "1=1")


def _policy_loosened(f: DriftFinding, _: Any, __: Any) -> bool:
    """A row-level-security policy now lets more rows through than the migrations say.

    New or changed permissive policy that is always true (or open to PUBLIC when it was not), a
    condition that disappeared, or a restrictive policy made permissive.
    """
    after, before = f.after, f.before
    if f.resource_type != "pg_policy" or not isinstance(after, dict) or f.change_kind == "deleted":
        return False
    if not after.get("permissive", True):
        return False
    if _always_true(after.get("using")) or _always_true(after.get("with_check")):
        return not isinstance(before, dict) or not (
            _always_true(before.get("using")) or _always_true(before.get("with_check"))
        )
    if not isinstance(before, dict):
        return False
    opened = "public" in after.get("roles", []) and "public" not in before.get("roles", [])
    dropped_condition = before.get("using") is not None and after.get("using") is None
    return opened or dropped_condition or not before.get("permissive", True)


Predicate = Callable[[DriftFinding, Any, Any], bool]
PREDICATES: dict[str, Predicate] = {
    "null_to_default": _null_to_default,
    "list_reordered": _list_reordered,
    "json_equal": _json_equal,
    "decreased": _decreased,
    "changed_to": _changed_to,
    "open_cidr_on_admin_port": _open_cidr_on_admin_port,
    "json_wildcard_principal": _json_wildcard_principal,
    "iam_wildcard": _iam_wildcard,
    "tags_all_mirrors_tags": _tags_all_mirrors_tags,
    "pii_name": _pii_name,
    "policy_loosened": _policy_loosened,
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


def _rule_pack(path: Path | None) -> dict[str, Any]:
    if path is None:
        text = resources.files("driftpilot.triage").joinpath("rules/default.yaml").read_text()
    else:
        text = path.read_text()
    return yaml.safe_load(text)


def needs_replace_to_revert(finding: DriftFinding, path: Path | None = None) -> bool:
    """True if reverting this attribute needs `apply -replace` rather than `-target`."""
    return any(
        glob_match(entry.get("type", "*"), finding.resource_type)
        and glob_match(entry.get("attribute", "*"), finding.attribute_path or "")
        for entry in _rule_pack(path).get("revert_with_replace", [])
    )


def _check_controls(controls: list[str]) -> None:
    unknown = set(controls) - CONTROL_TAGS
    if unknown:
        raise ValueError(
            f"unknown control tag: {sorted(unknown)} (allowed: {sorted(CONTROL_TAGS)})"
        )


def load_rules(path: Path | None = None) -> list[Rule]:
    rules = [Rule.model_validate(r) for r in _rule_pack(path)["rules"]]
    for rule in rules:
        _predicate(rule.when)  # fail fast on typos
        _check_controls(rule.controls)
    return rules


def _matches(
    pattern: RuleMatch | NeverSoften,
    when: str | dict[str, Any] | None,
    finding: DriftFinding,
    resource: Any,
) -> bool:
    if pattern.change_kind and finding.change_kind != pattern.change_kind:
        return False
    if not _glob(pattern.type).match(finding.resource_type):
        return False
    if pattern.attribute != "*" and not _glob(pattern.attribute).match(
        finding.attribute_path or ""
    ):
        return False
    predicate, arg = _predicate(when)
    return predicate is None or predicate(finding, arg, resource)


def rule_matches(rule: Rule, finding: DriftFinding, resource: Any = None) -> bool:
    return _matches(rule.match, rule.when, finding, resource)


def load_never_soften(path: Path | None = None) -> list[NeverSoften]:
    """The pack's `never_soften:` list (security weakenings an LLM verdict may not play down)."""
    entries = [NeverSoften.model_validate(e) for e in _rule_pack(path).get("never_soften") or []]
    for entry in entries:
        _predicate(entry.when)  # fail fast on typos
        _check_controls(entry.controls)
    return entries


def never_soften_for(
    finding: DriftFinding, entries: list[NeverSoften], resource: Any = None
) -> NeverSoften | None:
    """The matching entry with the highest floor, or None."""
    hits = [e for e in entries if _matches(e, e.when, finding, resource)]
    return max(hits, key=lambda e: SEVERITY_RANK[e.floor_severity], default=None)


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
                    controls=rule.controls,
                    **rule.verdict.model_dump(),
                )
                break
    return verdicts
