"""`metrics.prom`: the dashboard's numbers in the Prometheus text format (version 0.0.4).

Built from the same dict as `data.json`, so the two always agree. Prometheus (or Grafana Agent,
Alloy, a pushgateway job) can scrape the published file. The values are as of the last scan, not
live: the file only changes when a scan runs.
"""

import math
from collections import Counter
from datetime import datetime

CONTENT_TYPE = "text/plain; version=0.0.4"


def escape_label(value: object) -> str:
    """A label value as the exposition format wants it: `\\`, `"` and newlines escaped."""
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _labels(**labels: object) -> str:
    if not labels:
        return ""
    return "{" + ",".join(f'{k}="{escape_label(v)}"' for k, v in labels.items()) + "}"


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else repr(round(float(value), 6))


def _seconds(iso: str | None) -> float | None:
    if not iso:
        return None
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


class _Out:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def family(
        self, name: str, kind: str, help_text: str, samples: list[tuple[str, float]]
    ) -> None:
        """A metric family; with no samples the HELP/TYPE lines are still written."""
        self.lines += [f"# HELP {name} {help_text}", f"# TYPE {name} {kind}"]
        self.lines += [
            f"{name}{labels} {_number(value)}"
            for labels, value in samples
            if value is not None and math.isfinite(value)
        ]


def build_metrics(data: dict) -> str:
    """The Prometheus text for a `data.json` dict (ends with a newline)."""
    out = _Out()
    episodes = data.get("episodes", [])
    key = ("severity", "team", "driftType", "repo")

    def grouped(rows: list[dict]) -> list[tuple[str, float]]:
        counts = Counter(tuple(e[k] for k in key) for e in rows)
        return [
            (_labels(severity=s, team=t, drift_type=d, repo=r), n)
            for (s, t, d, r), n in sorted(counts.items())
        ]

    out.family(
        "driftpilot_open_episodes", "gauge",
        "Drift episodes still open at the latest scan.",
        grouped([e for e in episodes if not e["resolved"]]),
    )  # fmt: skip
    out.family(
        "driftpilot_episodes_total", "counter",
        "Drift episodes seen in the recorded history.",
        grouped(episodes),
    )  # fmt: skip
    kpis = data.get("kpis", {})

    def ratio(name: str, help_text: str, percent: float | None) -> None:
        out.family(name, "gauge", help_text, [] if percent is None else [("", percent / 100)])

    ratio("driftpilot_iac_coverage_ratio", "Managed resources / all resources (0 to 1).",
          kpis.get("iacCoverage"))  # fmt: skip
    ratio("driftpilot_drift_rate_ratio", "Distinct drifted resources / managed resources.",
          kpis.get("driftRate"))  # fmt: skip
    mttr = kpis.get("mttrHours")
    out.family(
        "driftpilot_mean_time_to_resolve_hours", "gauge",
        "Mean hours from first seen to the first scan without the drift.",
        [] if mttr is None else [("", mttr)],
    )  # fmt: skip
    ratio("driftpilot_overrule_ratio", "Share of decided findings a person overruled (0 to 1).",
          kpis.get("overruleRate"))  # fmt: skip

    last: dict[tuple[str, str], float] = {}
    streams = data.get("scans", {}).get("streams", [])
    for s in streams:
        stamp = _seconds(s.get("lastRun"))
        if stamp is not None:
            k = (s["repo"], s["driftType"])
            last[k] = max(stamp, last.get(k, 0))
    out.family(
        "driftpilot_scan_last_timestamp_seconds", "gauge",
        "Unix time of the latest recorded scan.",
        [(_labels(repo=r, drift_type=d), v) for (r, d), v in sorted(last.items())],
    )  # fmt: skip
    out.family(
        "driftpilot_scan_errors_7d", "gauge",
        "Errors reported by scans in the 7 days before the latest scan.",
        [("", sum(s.get("errors7d", 0) for s in streams))] if streams else [],
    )  # fmt: skip
    out.family(
        "driftpilot_monitor_alerts", "gauge",
        "Active alerts from the verdict monitor (is DriftPilot's judgment drifting?).",
        [("", len(data.get("monitor", {}).get("alerts", [])))],
    )  # fmt: skip
    return "\n".join(out.lines) + "\n"
