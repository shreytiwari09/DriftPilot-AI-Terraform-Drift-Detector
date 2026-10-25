import json
from pathlib import Path

import pytest

from driftpilot.evaluation.dataset import Case, load_cases
from driftpilot.evaluation.runner import SETUPS, CachingLLM, run_case, run_setup
from driftpilot.triage.llm import FakeLLM

ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
CASES = load_cases(ROOT / "eval" / "cases")
SETUP = {s.name: s for s in SETUPS}


def test_dataset_is_complete_and_every_finding_is_labelled() -> None:
    assert len(CASES) >= 70
    result = run_setup(CASES, SETUP["rules only"], None, ROOT, FIXTURES)  # raises if unlabelled
    real = [i for i in result.items if i.label_real]
    assert len(real) >= 60 and any(i.label_severity == "critical" for i in real)
    covered = set()
    for c in CASES:
        covered |= set(c.scenario) if isinstance(c.scenario, list) else {c.scenario}
    assert covered >= set(range(1, 15))  # all 14 SPEC scenarios


def test_raw_terraform_reports_everything_and_misses_unmanaged() -> None:
    m = run_setup(CASES, SETUP["raw terraform"], None, ROOT, FIXTURES).metrics()
    assert m["noise_reduction"] == 0 and m["severity_accuracy"] == 0
    assert m["real_drift_recall"] < 1  # unmanaged resources are invisible to a plan


def test_rules_only_scores() -> None:
    m = run_setup(CASES, SETUP["rules only"], None, ROOT, FIXTURES).metrics()
    assert m["noise_reduction"] > 0.9 and m["real_drift_recall"] == 1


def test_unlabelled_finding_is_an_error() -> None:
    case = Case.model_validate(
        {
            "id": "x",
            "source": "synthetic",
            "drift": [{"address": "aws_instance.a", "before": {"x": 1}, "after": {"x": 2}}],
            "expect": [],
        }
    )
    with pytest.raises(ValueError, match="no label"):
        run_case(case, SETUP["rules only"], None, ROOT, FIXTURES)


def test_llm_setup_uses_cache(tmp_path) -> None:
    case = next(c for c in CASES if c.id == "docker-cache-memory-raised")
    answer = json.dumps(
        {
            "verdicts": [
                {
                    "attribute_path": "memory",
                    "is_real_drift": True,
                    "severity": "medium",
                    "category": "availability",
                    "intent": "likely_hotfix",
                    "recommended_action": "codify",
                    "confidence": 0.9,
                    "reason": "r",
                }
            ]
        }
    )
    fake = FakeLLM([answer])
    first = CachingLLM(fake, tmp_path)
    [item] = run_case(case, SETUP["rules + cloud LLM"], first, ROOT, FIXTURES)
    assert (item.pred_action, item.source, first.calls) == ("codify", "llm", 1)
    again = CachingLLM(FakeLLM([]), tmp_path)  # no answers left: must come from the cache
    [item] = run_case(case, SETUP["rules + cloud LLM"], again, ROOT, FIXTURES)
    assert (item.pred_action, again.calls, again.hits) == ("codify", 0, 1)
