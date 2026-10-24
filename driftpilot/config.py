"""Load `.driftpilot.yml` (SPEC §5.2). A missing file means all defaults."""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from driftpilot.models import Severity

CONFIG_FILENAME = ".driftpilot.yml"


class SeverityOverride(BaseModel):
    match: dict[str, str]  # keys: type, attribute (glob patterns)
    severity: Severity


class LLMConfig(BaseModel):
    provider: str = "gemini"
    model: str | None = None
    temperature: float = 0.1


class DockerScannerConfig(BaseModel):
    enabled: bool = True
    managed_label: str = "managed-by=terraform"
    ignore_names: list[str] = []


class GitHubScannerConfig(BaseModel):
    enabled: bool = True
    owner: str
    ignore_names: list[str] = []


class ScannersConfig(BaseModel):
    docker: DockerScannerConfig | None = None
    github: GitHubScannerConfig | None = None


class Config(BaseModel):
    severity_overrides: list[SeverityOverride] = []
    ignore: list[str] = []  # address/attribute globs, e.g. "docker_container.*.restart"
    confidence_threshold: float = Field(default=0.7, ge=0, le=1)
    max_codify_retries: int = 3
    llm: LLMConfig = LLMConfig()
    scanners: ScannersConfig = ScannersConfig()


def load_config(path: Path | None, working_dir: Path) -> Config:
    """Load config from `path`, or from `<working_dir>/.driftpilot.yml` if it exists."""
    if path is None:
        path = working_dir / CONFIG_FILENAME
        if not path.exists():
            return Config()
    data = yaml.safe_load(path.read_text()) or {}
    return Config.model_validate(data)
