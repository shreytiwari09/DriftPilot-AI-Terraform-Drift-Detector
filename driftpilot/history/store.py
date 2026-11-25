"""Drift history: events + runs as JSON Lines, locally or on a data branch (SPEC §4.6)."""

from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel

from driftpilot.models import AuditRecord, HistoryEvent, RunRecord, ScanResult, Verdict
from driftpilot.report import counts

EVENTS_FILE = "drift-events.jsonl"
RUNS_FILE = "runs.jsonl"
AUDIT_FILE = "audit.jsonl"  # one line per LLM call: hashes and guardrail events, never text


def _parse(text: str, model: type[BaseModel]) -> list:
    return [model.model_validate_json(line) for line in text.splitlines() if line.strip()]


def _dump(items: list[BaseModel]) -> str:
    return "".join(item.model_dump_json() + "\n" for item in items)


class HistoryStore(Protocol):
    def load_events(self) -> list[HistoryEvent]: ...

    def load_runs(self) -> list[RunRecord]: ...

    def save(self, events: list[HistoryEvent], runs: list[RunRecord], message: str) -> None: ...

    def load_audit(self) -> list[AuditRecord]: ...

    def append_audit(self, records: list[AuditRecord], message: str) -> None: ...


class LocalStore:
    """`<dir>/drift-events.jsonl` and `<dir>/runs.jsonl` on disk (CLI mode)."""

    def __init__(self, directory: Path) -> None:
        self.dir = directory

    def _read(self, name: str) -> str:
        path = self.dir / name
        return path.read_text() if path.exists() else ""

    def load_events(self) -> list[HistoryEvent]:
        return _parse(self._read(EVENTS_FILE), HistoryEvent)

    def load_runs(self) -> list[RunRecord]:
        return _parse(self._read(RUNS_FILE), RunRecord)

    def save(self, events: list[HistoryEvent], runs: list[RunRecord], message: str = "") -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / EVENTS_FILE).write_text(_dump(events))
        (self.dir / RUNS_FILE).write_text(_dump(runs))

    def load_audit(self) -> list[AuditRecord]:
        return _parse(self._read(AUDIT_FILE), AuditRecord)

    def append_audit(self, records: list[AuditRecord], message: str = "") -> None:
        if not records:
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.dir / AUDIT_FILE, "a") as f:
            f.write(_dump(records))


class GitHubBranchStore:
    """The same files under `history/` on a data branch, via the GitHub API (Action mode).

    A separate branch keeps hundreds of data commits out of the code history.
    """

    def __init__(self, repo: Any, branch: str, folder: str = "history") -> None:
        self.repo = repo  # github.Repository
        self.branch = branch
        self.folder = folder

    def _path(self, name: str) -> str:
        return f"{self.folder}/{name}"

    def _ensure_branch(self) -> None:
        try:
            self.repo.get_branch(self.branch)
        except Exception as e:
            if getattr(e, "status", None) != 404:
                raise
            base = self.repo.get_branch(self.repo.default_branch).commit.sha
            self.repo.create_git_ref(ref=f"refs/heads/{self.branch}", sha=base)

    def _get(self, name: str) -> Any | None:
        try:
            return self.repo.get_contents(self._path(name), ref=self.branch)
        except Exception as e:
            if getattr(e, "status", None) == 404:
                return None
            raise

    def _read(self, name: str) -> str:
        content = self._get(name)
        return content.decoded_content.decode() if content is not None else ""

    def load_events(self) -> list[HistoryEvent]:
        return _parse(self._read(EVENTS_FILE), HistoryEvent)

    def load_runs(self) -> list[RunRecord]:
        return _parse(self._read(RUNS_FILE), RunRecord)

    def save(self, events: list[HistoryEvent], runs: list[RunRecord], message: str) -> None:
        self._ensure_branch()
        for name, text in ((EVENTS_FILE, _dump(events)), (RUNS_FILE, _dump(runs))):
            existing = self._get(name)
            if existing is None:
                self.repo.create_file(self._path(name), message, text, branch=self.branch)
            elif existing.decoded_content.decode() != text:
                self.repo.update_file(
                    self._path(name), message, text, existing.sha, branch=self.branch
                )

    def load_audit(self) -> list[AuditRecord]:
        return _parse(self._read(AUDIT_FILE), AuditRecord)

    def append_audit(self, records: list[AuditRecord], message: str) -> None:
        if not records:
            return
        self._ensure_branch()
        existing = self._get(AUDIT_FILE)
        if existing is None:
            self.repo.create_file(
                self._path(AUDIT_FILE), message, _dump(records), branch=self.branch
            )
        else:
            text = existing.decoded_content.decode() + _dump(records)
            self.repo.update_file(
                self._path(AUDIT_FILE), message, text, existing.sha, branch=self.branch
            )


def _untriaged(finding_id: str) -> Verdict:
    return Verdict(
        finding_id=finding_id,
        source="policy",
        is_real_drift=True,
        severity="medium",
        category="security",
        intent="unknown",
        recommended_action="investigate",
        confidence=0.0,
        reason="Not triaged (no rule matched and no LLM was configured).",
    )


def records_from_scan(result: ScanResult) -> tuple[list[HistoryEvent], RunRecord]:
    """History lines for one scan: an event per real finding / unmanaged resource, plus the run."""
    by_finding = {fid: r for r in result.remediations for fid in (r.finding_ids or [r.finding_id])}
    events = [
        HistoryEvent(
            run_id=result.run_id,
            timestamp=result.started_at,
            finding=f,
            verdict=result.verdicts.get(f.id) or _untriaged(f.id),
            remediation=by_finding.get(f.id),
            context=result.context.model_copy(
                update={"team": result.teams.get(f.id, result.context.team)}
            ),
        )
        for f in [*result.real_findings, *result.unmanaged]
    ]
    unmanaged_by_team: dict[str, int] = {}
    for u in result.unmanaged:
        team = result.teams.get(u.id, result.context.team)
        unmanaged_by_team[team] = unmanaged_by_team.get(team, 0) + 1
    c = counts(result)
    run = RunRecord(
        run_id=result.run_id,
        timestamp=result.started_at,
        working_dir=result.working_dir,
        finding_count=len(result.real_findings),
        critical_count=c["critical"],
        distinct_resources=len({f.address for f in result.real_findings}),
        unmanaged_count=len(result.unmanaged),
        noise_count=c["noise"],
        managed_resource_count=result.managed_resource_count,
        repo=result.context.repo,
        environment=result.context.environment,
        drift_type=result.context.drift_type,
        managed_by_team=result.managed_by_team,
        unmanaged_by_team=unmanaged_by_team,
        errors=len(result.errors),
    )
    return events, run


def append_scan(store: HistoryStore, result: ScanResult) -> None:
    events, run = records_from_scan(result)
    message = f"DriftPilot history: run {result.run_id} ({len(events)} event(s))"
    store.save([*store.load_events(), *events], [*store.load_runs(), run], message)
    store.append_audit(result.audit, message)
