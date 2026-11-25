"""SARIF 2.1.0 output for `driftpilot scan --sarif FILE`, so drift shows up in code scanning.

One rule per rule id, one result per real finding (noise and unmanaged resources are left out).
The Terraform address (or database object) is a logical location. A SARIF result also needs a
file location for GitHub's code scanning, so the scanned folder is given as the artifact. Text
comes from the verdict's reason, cleaned with `sanitize_text`; values and secrets are never
written.
"""

import json
from pathlib import PurePosixPath

from driftpilot import __version__
from driftpilot.guardrails import sanitize_text
from driftpilot.models import ScanResult
from driftpilot.ownership import mask_ids

INFO_URI = "https://github.com/shreytiwari09/DriftPilot-AI-Terraform-Drift-Detector"
SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
LEVELS = {"critical": "error", "high": "error", "medium": "warning", "low": "note", "none": "none"}
UNDECIDED_RULE = "driftpilot.undecided"


def _rule_id(verdict) -> str:
    if verdict is None:
        return UNDECIDED_RULE
    return verdict.rule_id or f"driftpilot.{verdict.source}"


def _folder(working_dir: str) -> str:
    """A relative folder for the artifact URI ("." when the path is absolute or climbs up)."""
    path = PurePosixPath(working_dir.replace("\\", "/"))
    return "." if path.is_absolute() or ".." in path.parts or not path.parts else path.as_posix()


def _clean(text: str, limit: int = 400) -> str:
    return sanitize_text(mask_ids(text), limit)


def build_sarif(result: ScanResult) -> dict:
    """The SARIF log (a dict) for one scan result."""
    rules: dict[str, dict] = {}
    results = []
    uri = _folder(result.working_dir)
    for f in result.real_findings:
        verdict = result.verdicts.get(f.id)
        rule_id = _rule_id(verdict)
        severity = verdict.severity if verdict else "medium"
        rules.setdefault(
            rule_id,
            {
                "id": rule_id,
                "name": rule_id,
                "shortDescription": {"text": f"DriftPilot: {rule_id}"},
                "defaultConfiguration": {"level": LEVELS[severity]},
            },
        )
        reason = verdict.reason if verdict else "Not triaged yet: no rule matched."
        attribute = f.attribute_path
        results.append(
            {
                "ruleId": rule_id,
                "level": LEVELS[severity],
                "message": {"text": _clean(reason)},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": uri},
                            "region": {"startLine": 1},
                        },
                        "logicalLocations": [
                            {
                                "name": _clean(attribute or f.address, 120),
                                "fullyQualifiedName": _clean(f.address, 200),
                                "kind": "resource",
                            }
                        ],
                    }
                ],
                "partialFingerprints": {"driftpilot/findingId": f.id},
                "properties": {
                    "severity": severity,
                    "action": verdict.recommended_action if verdict else "investigate",
                    "attribute": _clean(attribute, 120) if attribute else None,
                },
            }
        )
    return {
        "$schema": SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "DriftPilot",
                        "version": __version__,
                        "informationUri": INFO_URI,
                        "rules": list(rules.values()),
                    }
                },
                "results": results,
            }
        ],
    }


def sarif_text(result: ScanResult) -> str:
    return json.dumps(build_sarif(result), indent=2) + "\n"
