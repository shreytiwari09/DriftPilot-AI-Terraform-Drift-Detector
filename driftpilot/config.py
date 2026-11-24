"""Load `.driftpilot.yml` (SPEC §5.2). A missing file means all defaults."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from driftpilot.models import Severity

CONFIG_FILENAME = ".driftpilot.yml"


class SeverityOverride(BaseModel):
    match: dict[str, str]  # keys: type, attribute (glob patterns)
    severity: Severity


class LLMConfig(BaseModel):
    enabled: bool = True  # off, or no API key: undecided findings stay "needs triage"
    provider: Literal["gemini", "ollama"] = "gemini"
    model: str | None = None  # None = the provider client's default
    temperature: float = 0.0  # judgments should be as repeatable as possible
    base_url: str = "http://localhost:11434"  # Ollama only


class DockerScannerConfig(BaseModel):
    enabled: bool = True
    managed_label: str = "managed-by=terraform"
    include_names: list[str] = ["*"]  # which resources this repo's Terraform should own
    ignore_names: list[str] = []


class GitHubScannerConfig(BaseModel):
    enabled: bool = True
    owner: str
    # Org with several Terraform setups: scan only the names this repo should own.
    include_names: list[str] = ["*"]
    ignore_names: list[str] = []


class AWSScannerConfig(BaseModel):
    enabled: bool = True
    region: str = "us-east-1"
    include_names: list[str] = ["*"]
    ignore_names: list[str] = []
    resource_types: list[Literal["s3_bucket", "security_group", "iam_user"]] = [
        "s3_bucket",
        "security_group",
        "iam_user",
    ]


class ScannersConfig(BaseModel):
    docker: DockerScannerConfig | None = None
    github: GitHubScannerConfig | None = None
    aws: AWSScannerConfig | None = None


class GuardrailsConfig(BaseModel):
    """Content guardrails. Off only to measure their effect (the evaluation); limits stay on."""

    enabled: bool = True


class LimitsConfig(BaseModel):
    """Hard caps that bound what a run can cost or change, even if an LLM misbehaves."""

    max_llm_calls: int = Field(default=60, ge=0)
    max_prompt_chars: int = Field(default=300_000, ge=0)
    max_prs: int = Field(default=5, ge=0)
    max_files_per_pr: int = Field(default=3, ge=1)
    max_patch_lines: int = Field(default=300, ge=1)


class TeamRule(BaseModel):
    match: str  # glob on the resource address, e.g. "github_repository.payments-*"
    team: str


class OwnershipConfig(BaseModel):
    """Who owns what, and where this repo's Terraform runs (shown as filters on the dashboard)."""

    teams: list[TeamRule] = []
    default_team: str | None = None
    environment: str | None = None
    account: str | None = None
    repo: str | None = None  # default: $GITHUB_REPOSITORY


class DashboardLinks(BaseModel):
    """Where the dashboard's action links point. Unset values default to what history contains."""

    repo: str | None = None  # "owner/name" of the repo that runs DriftPilot
    workflow: str | None = None  # workflow file name, default "driftpilot.yml"
    branch: str | None = None  # branch that holds .driftpilot.yml, default "main"


class DashboardConfig(BaseModel):
    publish_addresses: bool = True  # false: resource addresses become stable hashes in data.json
    links: DashboardLinks = DashboardLinks()


class DatabaseConfig(BaseModel):
    """Postgres schema drift: migration files against a live database (`driftpilot db ...`)."""

    migrations: str = "migrations"  # folder with the `*.sql` migration files, relative to --dir
    url_env: str = "DRIFTPILOT_DB_URL"  # env var with the live database URL (read-only role)
    scratch_url_env: str = "DRIFTPILOT_SCRATCH_DB_URL"  # server where scratch databases are made
    schemas: list[str] = ["public"]
    ignore: list[str] = []  # globs on `schema.table` that are left out of both catalogs


class Config(BaseModel):
    severity_overrides: list[SeverityOverride] = []
    ignore: list[str] = []  # address/attribute globs, e.g. "docker_container.*.restart"
    confidence_threshold: float = Field(default=0.7, ge=0, le=1)
    max_codify_retries: int = 3
    mode: Literal["advise", "open-prs"] = "advise"  # advise = issues only, never PRs
    llm: LLMConfig = LLMConfig()
    scanners: ScannersConfig = ScannersConfig()
    guardrails: GuardrailsConfig = GuardrailsConfig()
    limits: LimitsConfig = LimitsConfig()
    ownership: OwnershipConfig = OwnershipConfig()
    dashboard: DashboardConfig = DashboardConfig()
    database: DatabaseConfig = DatabaseConfig()


def load_config(path: Path | None, working_dir: Path) -> Config:
    """Load config from `path`, or from `<working_dir>/.driftpilot.yml` if it exists."""
    if path is None:
        path = working_dir / CONFIG_FILENAME
        if not path.exists():
            return Config()
    data = yaml.safe_load(path.read_text()) or {}
    return Config.model_validate(data)
