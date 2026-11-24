import json
from pathlib import Path

import pytest
from pg_shop import shop
from test_evaluation import AlwaysNotReal

from driftpilot.evaluation.dataset import (
    DatabaseInput,
    apply_edit,
    load_adversarial,
    load_cases,
    load_database,
)
from driftpilot.evaluation.report import DATABASE_HEADING, database_markdown, splice_section
from driftpilot.evaluation.runner import DATABASE_SETUPS, CachingLLM, Setup, run_setup

ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
CASES = load_database(ROOT / "eval" / "cases")
SETUP = {s.name: s for s in DATABASE_SETUPS}


def test_database_cases_load_separately_and_cover_the_kinds_of_drift() -> None:
    assert 15 <= len(CASES) <= 40
    assert all(c.file == "database.yaml" and c.database is not None for c in CASES)
    assert not any(c.file == "database.yaml" for c in load_cases(ROOT / "eval" / "cases"))
    assert not any(c.file == "database.yaml" for c in load_adversarial(ROOT / "eval" / "cases"))
    assert any(c.default == "noise" for c in CASES)
    assert any("injection" in c.id for c in CASES)
    assert {c.scenario for c in CASES if c.scenario} == {15, 16, 17, 18}


def test_every_database_finding_is_labelled_and_every_label_is_produced() -> None:
    result = run_setup(CASES, SETUP["rules only"], None, ROOT, FIXTURES)  # raises if not
    real = [i for i in result.items if i.label_real]
    assert len(real) >= 25 and sum(i.label_severity == "critical" for i in real) >= 6
    assert {i.label_severity for i in real} == {"critical", "high", "medium", "low"}


def test_rules_decide_the_security_weakenings_and_leave_the_rest_to_the_ai() -> None:
    result = run_setup(CASES, SETUP["rules only"], None, ROOT, FIXTURES)
    critical = [i for i in result.items if i.label_severity == "critical" and i.label_real]
    assert all(i.pred_severity == "critical" and i.pred_action == "revert" for i in critical)
    assert all(i.never_soften for i in critical)
    m = result.metrics()
    assert m["critical_recall"] == 1 and m["real_drift_recall"] == 1
    undecided = [i for i in result.items if i.label_real and i.pred_severity is None]
    assert 5 <= len(undecided) <= 12


def test_the_raw_diff_reports_everything_with_no_judgement() -> None:
    m = run_setup(CASES, SETUP["raw schema diff"], None, ROOT, FIXTURES).metrics()
    assert m["noise_reduction"] == 0 and m["severity_accuracy"] == 0 and m["false_alarm_rate"] == 1


def test_noise_cases_are_filtered_by_rules() -> None:
    rules = run_setup(CASES, SETUP["rules only"], None, ROOT, FIXTURES)
    for case_id in ("db-noise-owner-and-comments", "db-noise-owner-only"):
        items = [i for i in rules.items if i.case_id == case_id]
        assert items and not any(i.pred_real for i in items)


def test_a_fooled_model_cannot_soften_a_postgres_weakening(tmp_path) -> None:
    """No rules at all and an LLM that calls everything noise: the guardrails still hold."""
    llm_only = Setup("llm only", rules=False, llm="cloud")
    result = run_setup(CASES, llm_only, CachingLLM(AlwaysNotReal(), tmp_path), ROOT, FIXTURES)
    weakenings = [i for i in result.items if i.never_soften and i.label_real]
    assert len(weakenings) >= 6
    assert all(i.pred_real and i.pred_severity == "critical" for i in weakenings)
    assert all(i.pred_action == "revert" for i in weakenings)


def test_the_injection_case_never_ends_as_noise(tmp_path) -> None:
    llm_only = SETUP["rules + cloud LLM"]
    result = run_setup(CASES, llm_only, CachingLLM(AlwaysNotReal(), tmp_path), ROOT, FIXTURES)
    for case_id in ("db-injection-in-a-column-default", "db-injection-in-a-new-column-comment"):
        [item] = [i for i in result.items if i.case_id == case_id]
        assert item.pred_real and item.pred_action == "investigate"


def test_edit_steps_change_a_catalog_and_unknown_ones_fail() -> None:
    catalog = shop().model_copy(deep=True)
    apply_edit(
        catalog,
        {"op": "drop_grant", "table": "users", "grantee": "app_readonly", "privilege": "SELECT"},
    )
    assert catalog.table("public.users").grants == []
    with pytest.raises(ValueError, match="unknown database edit"):
        apply_edit(catalog, {"op": "explode", "table": "users"})
    with pytest.raises(ValueError, match="no table"):
        apply_edit(catalog, {"op": "drop_table", "table": "nope"})


def test_a_case_can_give_both_catalogs_in_place(tmp_path) -> None:
    from driftpilot.evaluation.dataset import Case

    live = shop().model_dump()
    live["tables"][0]["rls_enabled"] = False
    case = Case.model_validate(
        {
            "id": "x", "source": "synthetic",
            "database": DatabaseInput(expected=shop().model_dump(), live=live).model_dump(),
            "expect": [],
        }
    )  # fmt: skip
    [f] = case.database_findings(tmp_path)
    assert f.attribute_path == "row_level_security"


def test_a_database_case_with_two_inputs_is_rejected(tmp_path) -> None:
    (tmp_path / "database.yaml").write_text(
        "- id: x\n  source: synthetic\n  database: {}\n"
        "  unmanaged: {provider: github, kind: r, name: n}\n  expect: []\n"
    )
    with pytest.raises(ValueError, match="exactly one"):
        load_database(tmp_path)


def test_the_report_has_a_table_and_the_misses_and_splices_into_a_summary() -> None:
    results = [
        run_setup(CASES, SETUP[n], None, ROOT, FIXTURES) for n in ("raw schema diff", "rules only")
    ]
    section = database_markdown(CASES, results)
    assert section.startswith(DATABASE_HEADING) and "| rules only |" in section
    assert "needs triage" in section and "Noise reported as drift" in section
    summary = "# Results\n\n## Other\n\ntext\n"
    once = splice_section(summary, section, DATABASE_HEADING)
    assert once.count(DATABASE_HEADING) == 1 and once.startswith("# Results")
    twice = splice_section(once + "\n## After\n\nx\n", section, DATABASE_HEADING)
    assert twice.count(DATABASE_HEADING) == 1 and "## After" in twice


def test_the_fake_model_sees_the_database_values(tmp_path) -> None:
    llm = AlwaysNotReal()
    case = [c for c in CASES if c.id == "db-column-default-changed"]
    run_setup(case, SETUP["rules + cloud LLM"], CachingLLM(llm, tmp_path), ROOT, FIXTURES)
    [prompt] = llm.prompts
    data = json.loads(prompt.split("\n", 1)[1])
    assert data["address"] == "postgres.public.orders.status"
    assert data["changes"][0]["before"] == "'new'" and data["changes"][0]["after"] == "'open'"
