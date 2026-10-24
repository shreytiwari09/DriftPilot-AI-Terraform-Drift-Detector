"""Is DriftPilot's own judgment drifting? (SPEC §4.6 verdict monitor — concept drift)

Watches the human overrule rate and the mix of DriftPilot's verdicts. A breach means rules or the
prompt need a human review.
"""

from datetime import datetime, timedelta

import pandas as pd
from pydantic import BaseModel

from driftpilot.history.analytics import BASELINE_DAYS, PSI_ALERT, RECENT_DAYS, psi

OVERRULE_ALERT = 0.25  # more than 1 in 4 decided verdicts overruled lately


class MonitorReport(BaseModel):
    weekly_overrule_rate: dict[str, float]  # ISO week start → rate (decided episodes only)
    recent_overrule_rate: float | None
    baseline_overrule_rate: float | None
    recent_decided: int
    verdict_psi: dict[str, float]  # "severity" / "action" → PSI recent vs baseline
    alerts: list[str]

    @property
    def breached(self) -> bool:
        return bool(self.alerts)


def _rate(frame: pd.DataFrame) -> tuple[float | None, int]:
    decided = frame[frame["outcome"].isin(["accepted", "overruled"])]
    if not len(decided):
        return None, 0
    return round(float((decided["outcome"] == "overruled").mean()), 3), len(decided)


def monitor(episodes: pd.DataFrame, now: datetime, min_decided: int = 5) -> MonitorReport:
    if not len(episodes):
        return MonitorReport(
            weekly_overrule_rate={},
            recent_overrule_rate=None,
            baseline_overrule_rate=None,
            recent_decided=0,
            verdict_psi={},
            alerts=[],
        )
    start = pd.to_datetime(episodes["start"], utc=True)
    week = start.dt.tz_localize(None).dt.to_period("W").dt.start_time.dt.date.astype(str)
    weekly = {}
    for wk, group in episodes.groupby(week):
        rate, _ = _rate(group)
        if rate is not None:
            weekly[wk] = rate

    recent_from = now - timedelta(RECENT_DAYS)
    recent = episodes[start >= recent_from]
    baseline = episodes[(start < recent_from) & (start >= recent_from - timedelta(BASELINE_DAYS))]
    recent_rate, recent_n = _rate(recent)
    baseline_rate, _ = _rate(baseline)

    verdict_psi = {}
    if len(recent) and len(baseline):
        for dim in ("severity", "action"):
            verdict_psi[dim] = round(
                psi(baseline[dim].value_counts(), recent[dim].value_counts()), 3
            )

    alerts = []
    if recent_rate is not None and recent_n >= min_decided and recent_rate > OVERRULE_ALERT:
        was = f" (was {baseline_rate:.0%})" if baseline_rate is not None else ""
        alerts.append(
            f"Humans overruled {recent_rate:.0%} of DriftPilot's decided verdicts in the last "
            f"{RECENT_DAYS} days{was}; threshold {OVERRULE_ALERT:.0%}."
        )
    for dim, value in verdict_psi.items():
        if value > PSI_ALERT:
            alerts.append(
                f"The mix of verdict {dim} values shifted (PSI {value:.2f} > {PSI_ALERT}) "
                f"compared with the previous {BASELINE_DAYS} days."
            )
    return MonitorReport(
        weekly_overrule_rate=weekly,
        recent_overrule_rate=recent_rate,
        baseline_overrule_rate=baseline_rate,
        recent_decided=recent_n,
        verdict_psi=verdict_psi,
        alerts=alerts,
    )


def alert_issue_body(report: MonitorReport) -> str:
    lines = [
        "DriftPilot's verdict monitor found signs that its own judgment may be drifting:",
        "",
        *[f"- {a}" for a in report.alerts],
        "",
        "Recommended: review recent overruled issues/PRs, then adjust the rule pack "
        "(`triage/rules/default.yaml`) or the triage prompt, and re-run the evaluation.",
    ]
    return "\n".join(lines)
