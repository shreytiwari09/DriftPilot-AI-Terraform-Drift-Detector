"""Minimal `.env` loader for local runs, so secrets like GEMINI_API_KEY stay out of code and git."""

import os
from pathlib import Path


def load_env_file(path: Path = Path(".env")) -> list[str]:
    """Set variables from a `.env` file. Real environment variables win; empty values are skipped.

    Returns the names that were set (never the values).
    """
    if not path.is_file():
        return []
    loaded = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.removeprefix("export ").split("=", 1)
        name, value = name.strip(), value.strip().strip("'\"")
        if value and name not in os.environ:
            os.environ[name] = value
            loaded.append(name)
    return loaded
