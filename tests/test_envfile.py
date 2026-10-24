import os
from pathlib import Path

from driftpilot.envfile import load_env_file


def test_loads_values_skips_comments_and_empty(tmp_path: Path, monkeypatch) -> None:
    for name in ("DP_A", "DP_B", "DP_EMPTY"):
        monkeypatch.delenv(name, raising=False)
    env = tmp_path / ".env"
    env.write_text("# comment\nDP_A=one\nexport DP_B='two'\nDP_EMPTY=\nnot a line\n")
    assert load_env_file(env) == ["DP_A", "DP_B"]
    assert os.environ["DP_A"] == "one"
    assert os.environ["DP_B"] == "two"
    assert "DP_EMPTY" not in os.environ


def test_real_environment_wins(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DP_A", "from-shell")
    env = tmp_path / ".env"
    env.write_text("DP_A=from-file\n")
    assert load_env_file(env) == []
    assert os.environ["DP_A"] == "from-shell"


def test_missing_file(tmp_path: Path) -> None:
    assert load_env_file(tmp_path / "nope") == []
