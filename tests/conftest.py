import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def outputs_file_in_tmp(monkeypatch, tmp_path) -> None:
    """`driftpilot action` outside GitHub writes an outputs file: never into the repo."""
    monkeypatch.setenv("DRIFTPILOT_OUTPUTS_FILE", str(tmp_path / "driftpilot-outputs.json"))


@pytest.fixture(autouse=True)
def no_real_llm(monkeypatch) -> None:
    """Unit tests make no network calls: never load .env or see a real LLM key."""
    monkeypatch.setattr("driftpilot.cli.load_env_file", lambda *a, **k: [])
    for name in ("GEMINI_API_KEY", "DRIFTPILOT_LLM_API_KEY", "DRIFTPILOT_LLM_PROVIDER"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def load_fixture() -> Callable[[str], dict[str, Any]]:
    """Load a recorded plan/state JSON, e.g. load_fixture("docker/s11_memory_changed")."""

    def _load(name: str) -> dict[str, Any]:
        return json.loads((FIXTURES / f"{name}.json").read_text())

    return _load


def pytest_collection_modifyitems(config, items) -> None:
    """`@pytest.mark.postgres` tests need a real server: skip them unless a test URL is given."""
    if os.environ.get("DRIFTPILOT_TEST_DB_URL"):
        return
    skip = pytest.mark.skip(reason="set DRIFTPILOT_TEST_DB_URL to run the live Postgres tests")
    for item in items:
        if "postgres" in item.keywords:
            item.add_marker(skip)
