from pathlib import Path

import pytest
from pydantic import ValidationError

from driftpilot.config import load_config


def test_missing_file_gives_defaults(tmp_path: Path) -> None:
    config = load_config(None, tmp_path)
    assert config.confidence_threshold == 0.7
    assert config.scanners.docker is None


def test_loads_file_from_working_dir(tmp_path: Path) -> None:
    (tmp_path / ".driftpilot.yml").write_text(
        """
ignore: ["docker_container.*.restart"]
scanners:
  github:
    owner: driftpilot-demo
    ignore_names: [infra]
"""
    )
    config = load_config(None, tmp_path)
    assert config.ignore == ["docker_container.*.restart"]
    assert config.scanners.github.owner == "driftpilot-demo"
    assert config.scanners.github.ignore_names == ["infra"]


def test_explicit_path_and_validation(tmp_path: Path) -> None:
    path = tmp_path / "custom.yml"
    path.write_text("confidence_threshold: 3\n")
    with pytest.raises(ValidationError):
        load_config(path, tmp_path)


def test_guardrails_and_limits_defaults(tmp_path: Path) -> None:
    config = load_config(None, tmp_path)
    assert config.guardrails.enabled is True
    limits = config.limits
    assert (limits.max_llm_calls, limits.max_prompt_chars) == (60, 300_000)
    assert (limits.max_prs, limits.max_files_per_pr, limits.max_patch_lines) == (5, 3, 300)


def test_guardrails_and_limits_from_file(tmp_path: Path) -> None:
    (tmp_path / ".driftpilot.yml").write_text(
        "guardrails: {enabled: false}\nlimits: {max_llm_calls: 3, max_prs: 0}\n"
    )
    config = load_config(None, tmp_path)
    assert config.guardrails.enabled is False
    assert (config.limits.max_llm_calls, config.limits.max_prs) == (3, 0)
    assert config.limits.max_patch_lines == 300  # untouched defaults stay
