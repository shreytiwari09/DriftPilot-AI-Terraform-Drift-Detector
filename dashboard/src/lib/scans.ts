// Is DriftPilot itself running on time? Status comes from the time since a stream's last scan
// compared with the expected cadence (`dashboard.scan_every_hours`), judged against the clock
// of the viewer. Data that says it is simulated is judged against its own latest scan instead.
import type { DashboardData, ScanStream } from '../types';

export type ScanStatus = 'on_time' | 'late' | 'stale';

export const ON_TIME_FACTOR = 1.5;
export const LATE_FACTOR = 3;
export const DEFAULT_CADENCE_HOURS = 6;
const HOUR = 3_600_000;

/** On time up to 1.5x the cadence, late up to 3x, stale beyond. */
export function scanStatus(hoursSinceLast: number, cadenceHours: number): ScanStatus {
  if (hoursSinceLast <= ON_TIME_FACTOR * cadenceHours) return 'on_time';
  return hoursSinceLast <= LATE_FACTOR * cadenceHours ? 'late' : 'stale';
}

export const STATUS_LABEL: Record<ScanStatus, string> = { on_time: 'On time', late: 'Late', stale: 'Stale' };

export const isSimulated = (note: string | null | undefined): boolean => !!note && /simulated/i.test(note);

/** The newest scan time in the data: the latest stream run, else `asOf`, else `generated`. */
export function latestScan(data: DashboardData): string | null {
  const runs = (data.scans?.streams ?? []).map((s) => s.lastRun).sort();
  return runs[runs.length - 1] ?? data.asOf ?? data.generated ?? null;
}

/** "Now" for the status maths: the real clock, except for simulated data (its own latest scan). */
export function referenceNow(data: DashboardData, now: Date): Date {
  if (isSimulated(data.note)) {
    const t = latestScan(data);
    if (t) return new Date(t);
  }
  return now;
}

export const cadenceOf = (data: DashboardData): number => {
  const h = data.scans?.expectedHours;
  return typeof h === 'number' && h > 0 ? h : DEFAULT_CADENCE_HOURS;
};

export const hoursSince = (iso: string, now: Date): number => (now.getTime() - Date.parse(iso)) / HOUR;

/** When the next scan is expected: the last one plus one cadence. */
export function nextExpected(lastIso: string, cadenceHours: number): Date {
  return new Date(Date.parse(lastIso) + cadenceHours * HOUR);
}

export interface StreamRow extends ScanStream {
  status: ScanStatus;
  hoursSinceLast: number;
}

export interface ScanSummary {
  rows: StreamRow[];
  onTime: number;
  total: number;
  runs24h: number;
  errors7d: number;
  longestGapHours: number;
}

type Where = Partial<{ repo: string; environment: string; driftType: string }>;

export function summarizeScans(data: DashboardData, now: Date, where: Where = {}): ScanSummary {
  const ref = referenceNow(data, now);
  const cadence = cadenceOf(data);
  const rows = (data.scans?.streams ?? [])
    .filter((s) => (!where.repo || s.repo === where.repo) && (!where.environment || s.environment === where.environment) && (!where.driftType || s.driftType === where.driftType))
    .map((s) => {
      const hoursSinceLast = Math.max(0, hoursSince(s.lastRun, ref));
      return { ...s, hoursSinceLast, status: scanStatus(hoursSinceLast, cadence) };
    });
  // Worst first, so a problem is the first row.
  const order: Record<ScanStatus, number> = { stale: 0, late: 1, on_time: 2 };
  rows.sort((a, b) => order[a.status] - order[b.status] || a.repo.localeCompare(b.repo) || a.driftType.localeCompare(b.driftType) || a.dir.localeCompare(b.dir));
  return {
    rows,
    onTime: rows.filter((r) => r.status === 'on_time').length,
    total: rows.length,
    runs24h: rows.reduce((a, r) => a + r.runCount24h, 0),
    errors7d: rows.reduce((a, r) => a + r.errors7d, 0),
    longestGapHours: rows.reduce((m, r) => Math.max(m, r.longestGapHours7d), 0),
  };
}

export interface RecentRow {
  t: string;
  stream: string;
  findings: number;
  critical: number;
  noise: number;
  errors: number;
}

export const streamName = (s: Pick<ScanStream, 'repo' | 'driftType' | 'environment' | 'dir'>): string => `${s.repo} · ${s.driftType} · ${s.environment}`;

/** The newest runs across the listed streams, newest first. */
export function recentRuns(rows: ScanStream[], limit = 30): RecentRow[] {
  return rows
    .flatMap((s) => s.recent.map((r) => ({ ...r, stream: streamName(s) })))
    .sort((a, b) => b.t.localeCompare(a.t) || a.stream.localeCompare(b.stream))
    .slice(0, limit);
}
