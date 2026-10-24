"""Statistics over drift history (SPEC §4.6).

Recurring drift, anomalies, distribution shifts, change-points and a health score.

Unfixed drift is re-detected every run, so analytics count *episodes* — a finding that starts
again after it was gone, or after its value changed — not detections.
"""

import json
import math
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
from pydantic import BaseModel

from driftpilot.models import DriftFinding, HistoryEvent, RunRecord

RECENT_DAYS, BASELINE_DAYS = 14, 56  # shift: last 2 weeks vs the 8 before
PSI_ALERT = 0.25  # rule of thumb: > 0.25 is a significant shift


class Recurring(BaseModel):
    address: str
    attribute: str | None
    episodes: int
    recommendation: str


class DayAnomaly(BaseModel):
    day: date
    new_episodes: int
    baseline_mean: float
    z: float


class RunAnomaly(BaseModel):
    run_id: str
    timestamp: datetime
    finding_count: int
    score: float  # IsolationForest decision score; lower = more unusual


class Shift(BaseModel):
    dimension: str  # "category" or "severity"
    psi: float
    chi2_p: float | None
    shifted: bool
    baseline: dict[str, float]  # share per value
    recent: dict[str, float]


class Health(BaseModel):
    runs: int
    pct_runs_zero_drift: float
    mean_hours_to_remediate: float | None
    pct_resources_ever_drifted: float | None


class AnalyticsReport(BaseModel):
    period_start: datetime | None
    period_end: datetime | None
    episodes: int
    daily_new_episodes: dict[date, int]
    recurring: list[Recurring]
    day_anomalies: list[DayAnomaly]
    run_anomalies: list[RunAnomaly]
    shifts: list[Shift]
    change_points: list[date]
    health: Health


def episodes_frame(events: list[HistoryEvent], runs: list[RunRecord]) -> pd.DataFrame:
    """One row per episode: when it started/ended, what it was, and how it was judged."""
    columns = [
        "finding_id", "address", "attribute", "start", "end", "runs_seen",
        "severity", "category", "action", "source", "outcome", "resolved",
    ]  # fmt: skip
    drift = [e for e in events if isinstance(e.finding, DriftFinding)]
    if not drift or not runs:
        return pd.DataFrame(columns=columns)
    order = {r.run_id: i for i, r in enumerate(sorted(runs, key=lambda r: r.timestamp))}
    last_run = len(order) - 1
    rows = []
    by_finding: dict[str, list[HistoryEvent]] = {}
    for e in drift:
        if e.run_id in order:
            by_finding.setdefault(e.finding.id, []).append(e)
    for fid, group in by_finding.items():
        group.sort(key=lambda e: order[e.run_id])
        current: list[HistoryEvent] = []
        for e in group:
            value = json.dumps(e.finding.after, sort_keys=True, default=str)
            if current:
                prev = current[-1]
                same_value = value == json.dumps(prev.finding.after, sort_keys=True, default=str)
                if order[e.run_id] == order[prev.run_id] + 1 and same_value:
                    current.append(e)
                    continue
                rows.append(_episode_row(fid, current, order, last_run))
            current = [e]
        rows.append(_episode_row(fid, current, order, last_run))
    return pd.DataFrame(rows, columns=columns).sort_values("start", ignore_index=True)


def _episode_row(fid: str, group: list[HistoryEvent], order: dict, last_run: int) -> dict:
    first, last = group[0], group[-1]
    outcomes = {e.human_outcome for e in group} - {"pending"}
    return {
        "finding_id": fid,
        "address": first.finding.address,
        "attribute": first.finding.attribute_path,
        "start": first.timestamp,
        "end": last.timestamp,
        "runs_seen": len(group),
        "severity": first.verdict.severity,
        "category": first.verdict.category,
        "action": first.verdict.recommended_action,
        "source": first.verdict.source,
        "outcome": outcomes.pop() if len(outcomes) == 1 else "pending",
        "resolved": order[last.run_id] < last_run,
    }


def daily_counts(episodes: pd.DataFrame, runs: list[RunRecord]) -> pd.Series:
    """New episodes per calendar day, including days with none."""
    if not runs:
        return pd.Series(dtype=int)
    days = pd.date_range(
        min(r.timestamp for r in runs).date(), max(r.timestamp for r in runs).date(), freq="D"
    ).date
    counts = pd.Series(0, index=days, dtype=int)
    if len(episodes):
        observed = pd.to_datetime(episodes["start"], utc=True).dt.date.value_counts()
        counts = counts.add(observed, fill_value=0).astype(int)
    return counts.sort_index()


def recurring(
    episodes: pd.DataFrame, now: datetime, window_days: int = 14, min_episodes: int = 3
) -> list[Recurring]:
    """Same (address, attribute) starting to drift ≥ min_episodes times in the window."""
    if not len(episodes):
        return []
    recent = episodes[pd.to_datetime(episodes["start"], utc=True) >= now - timedelta(window_days)]
    grouped = recent.groupby(["address", "attribute"], dropna=False).size()
    return [
        Recurring(
            address=address,
            attribute=None if pd.isna(attribute) else attribute,
            episodes=int(n),
            recommendation=(
                "This keeps being changed by hand. If the new value is intended, codify it or add "
                "lifecycle.ignore_changes; otherwise fix the process or automation that changes it."
            ),
        )
        for (address, attribute), n in grouped.items()
        if n >= min_episodes
    ]


def zscore_anomalies(
    daily: pd.Series, window: int = 14, threshold: float = 3.0, min_std: float = 1.0
) -> list[DayAnomaly]:
    """Days whose count is far above the previous `window` days (std floored for count data)."""
    if len(daily) <= window:
        return []
    history = daily.shift(1).rolling(window)
    mean, std = history.mean(), history.std().clip(lower=min_std)
    z = (daily - mean) / std
    return [
        DayAnomaly(
            day=d, new_episodes=int(daily[d]), baseline_mean=round(mean[d], 2), z=round(z[d], 1)
        )
        for d in daily.index
        if not math.isnan(z[d]) and z[d] > threshold
    ]


def run_anomalies(runs: list[RunRecord], contamination: float = 0.02) -> list[RunAnomaly]:
    """Isolation Forest over per-run vectors: finding count, critical count, resources, hour."""
    if len(runs) < 20:
        return []
    from sklearn.ensemble import IsolationForest

    features = np.array(
        [[r.finding_count, r.critical_count, r.distinct_resources, r.timestamp.hour] for r in runs]
    )
    model = IsolationForest(contamination=contamination, random_state=0).fit(features)
    scores, flags = model.decision_function(features), model.predict(features)
    return [
        RunAnomaly(
            run_id=r.run_id,
            timestamp=r.timestamp,
            finding_count=r.finding_count,
            score=round(float(s), 3),
        )
        for r, s, flag in zip(runs, scores, flags, strict=True)
        if flag == -1
    ]


def psi(baseline: pd.Series, recent: pd.Series, eps: float = 1e-4) -> float:
    """Population Stability Index between two count distributions over the same categories."""
    keys = baseline.index.union(recent.index)
    b = baseline.reindex(keys, fill_value=0) / max(baseline.sum(), 1)
    r = recent.reindex(keys, fill_value=0) / max(recent.sum(), 1)
    b, r = b.clip(lower=eps), r.clip(lower=eps)
    return float(((r - b) * np.log(r / b)).sum())


def distribution_shifts(episodes: pd.DataFrame, now: datetime) -> list[Shift]:
    """Category and severity mix: last RECENT_DAYS vs the BASELINE_DAYS before."""
    if not len(episodes):
        return []
    from scipy.stats import chi2_contingency

    start = pd.to_datetime(episodes["start"], utc=True)
    recent_from = now - timedelta(RECENT_DAYS)
    baseline_from = recent_from - timedelta(BASELINE_DAYS)
    recent = episodes[start >= recent_from]
    baseline = episodes[(start >= baseline_from) & (start < recent_from)]
    shifts = []
    for dim in ("category", "severity"):
        b, r = baseline[dim].value_counts(), recent[dim].value_counts()
        if b.sum() == 0 or r.sum() == 0:
            continue
        value = psi(b, r)
        table = pd.concat([b, r], axis=1).fillna(0).to_numpy().T
        p = None
        if table.shape[1] > 1:
            p = float(chi2_contingency(table)[1])
        shifts.append(
            Shift(
                dimension=dim,
                psi=round(value, 3),
                chi2_p=None if p is None else round(p, 4),
                shifted=value > PSI_ALERT or (p is not None and p < 0.01),
                baseline=(b / b.sum()).round(3).to_dict(),
                recent=(r / r.sum()).round(3).to_dict(),
            )
        )
    return shifts


def change_points(daily: pd.Series, penalty: float | None = None) -> list[date]:
    """Days where the level of daily drift changes (ruptures PELT)."""
    if len(daily) < 10:
        return []
    import ruptures

    x = daily.to_numpy(dtype=float)
    if penalty is None:
        # Scale the penalty by day-to-day noise estimated robustly (median absolute deviation of
        # differences), so one huge spike can't inflate it and hide itself; floor at Poisson noise.
        diffs = np.diff(x)
        mad = np.median(np.abs(diffs - np.median(diffs)))
        sigma = max(1.4826 * mad / np.sqrt(2), np.sqrt(max(x.mean(), 1.0)))
        penalty = 3 * sigma**2 * np.log(len(x))
    breaks = ruptures.Pelt(model="l2", min_size=1).fit(x.reshape(-1, 1)).predict(pen=penalty)
    return [daily.index[b] for b in breaks if b < len(daily)]


def health(episodes: pd.DataFrame, runs: list[RunRecord]) -> Health:
    zero = sum(r.finding_count == 0 and r.unmanaged_count == 0 for r in runs)
    mean_hours = None
    resolved = episodes[episodes["resolved"]] if len(episodes) else episodes
    if len(resolved):
        durations = pd.to_datetime(resolved["end"], utc=True) - pd.to_datetime(
            resolved["start"], utc=True
        )
        mean_hours = round(float(durations.dt.total_seconds().mean() / 3600), 1)
    managed = max((r.managed_resource_count or 0 for r in runs), default=0)
    ever = (
        round(100 * episodes["address"].nunique() / managed, 1)
        if managed and len(episodes)
        else None
    )
    return Health(
        runs=len(runs),
        pct_runs_zero_drift=round(100 * zero / len(runs), 1) if runs else 0.0,
        mean_hours_to_remediate=mean_hours,
        pct_resources_ever_drifted=ever,
    )


def analyze(
    events: list[HistoryEvent], runs: list[RunRecord], now: datetime | None = None
) -> AnalyticsReport:
    runs = sorted(runs, key=lambda r: r.timestamp)
    now = now or (runs[-1].timestamp if runs else datetime.now())
    eps = episodes_frame(events, runs)
    daily = daily_counts(eps, runs)
    return AnalyticsReport(
        period_start=runs[0].timestamp if runs else None,
        period_end=runs[-1].timestamp if runs else None,
        episodes=len(eps),
        daily_new_episodes={d: int(n) for d, n in daily.items()},
        recurring=recurring(eps, now),
        day_anomalies=zscore_anomalies(daily),
        run_anomalies=run_anomalies(runs),
        shifts=distribution_shifts(eps, now),
        change_points=change_points(daily),
        health=health(eps, runs),
    )
