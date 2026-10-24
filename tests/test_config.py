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
