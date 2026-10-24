import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def load_fixture() -> Callable[[str], dict[str, Any]]:
    """Load a recorded plan/state JSON, e.g. load_fixture("docker/s11_memory_changed")."""

    def _load(name: str) -> dict[str, Any]:
        return json.loads((FIXTURES / f"{name}.json").read_text())

    return _load
