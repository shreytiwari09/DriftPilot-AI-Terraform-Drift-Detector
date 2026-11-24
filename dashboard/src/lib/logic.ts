// The numbers behind every tile and chart. Mirrors driftpilot/report/dashboard/data.py
// (filter_episodes, compute_kpis, episodes_csv); tests/parity.test.ts checks both give the same.
import type { AuditRun, Episode, Filters, Kpis, RunRow } from '../types';

export const RECURRING_MIN = 3; // episodes of the same setting before it counts as a recurring offender

export const CSV_COLUMNS = [
  'start', 'resolvedAt', 'address', 'attribute', 'resourceType', 'team', 'repo', 'environment',
  'account', 'driftType', 'severity', 'category', 'action', 'decidedBy', 'outcome', 'resolved',
  'runsSeen',
] as const;

type Loose = Partial<Record<keyof Filters, string | undefined>>;

const inRange = (t: string, f: Loose): boolean => {
  const day = t.slice(0, 10);
  return (!f.from || day >= f.from) && (!f.to || day <= f.to);
};

export function filterEpisodes(episodes: Episode[], f: Loose): Episode[] {
  const needle = (f.search ?? '').trim().toLowerCase();
  const exact = ['team', 'repo', 'environment', 'driftType', 'severity', 'decidedBy', 'outcome'] as const;
  return episodes.filter((e) => {
    if (!inRange(e.start, f)) return false;
    if (exact.some((k) => f[k] && e[k] !== f[k])) return false;
    if (f.status === 'open' && e.resolved) return false;
    if (f.status === 'resolved' && !e.resolved) return false;
    if (needle) {
      const hay = [e.address, e.attribute, e.resourceType, e.team, e.repo].map((v) => v ?? '').join(' ');
      if (!hay.toLowerCase().includes(needle)) return false;
    }
    return true;
  });
}

function latestPerStream(runs: RunRow[], f: Loose): RunRow[] {
  const latest = new Map<string, RunRow>();
  for (const r of runs) {
    if ((['repo', 'environment', 'driftType'] as const).some((k) => f[k] && r[k] !== f[k])) continue;
    if (!inRange(r.t, f)) continue;
    const key = JSON.stringify([r.repo, r.environment, r.driftType, r.dir]);
    const seen = latest.get(key);
    if (!seen || r.t >= seen.t) latest.set(key, r);
  }
  return [...latest.values()];
}

function managedAndUnmanaged(runs: RunRow[], f: Loose): [number | null, number | null] {
  const latest = latestPerStream(runs, f);
  if (latest.length === 0) return [null, null];
  let managed = 0;
  let unmanaged = 0;
  for (const r of latest) {
    if (r.managed === null || r.managed === undefined) return [null, null];
    if (!f.team) {
      managed += r.managed;
      unmanaged += r.unmanaged;
    } else if (r.managedByTeam && Object.keys(r.managedByTeam).length > 0) {
      managed += r.managedByTeam[f.team] ?? 0;
      unmanaged += r.unmanagedByTeam?.[f.team] ?? 0;
    } else {
      return [null, null]; // run from before per-team counts: better "unknown" than wrong
    }
  }
  return [managed, unmanaged];
}

const round1 = (x: number): number => Math.round(x * 10) / 10;
const pct = (part: number, whole: number): number | null => (whole ? round1((100 * part) / whole) : null);
const hoursBetween = (a: string, b: string): number => (Date.parse(a) - Date.parse(b)) / 3_600_000;

export function computeKpis(episodes: Episode[], runs: RunRow[], f: Loose, asOf: string | null): Kpis {
  const eps = filterEpisodes(episodes, f);
  const [managed, unmanaged] = managedAndUnmanaged(runs, f);
  const drifted = new Set(eps.map((e) => e.address)).size;
  const open = eps.filter((e) => !e.resolved);
  let oldest: number | null = null;
  if (open.length && asOf) {
    const first = open.reduce((m, e) => (e.start < m ? e.start : m), open[0].start);
    oldest = round1(hoursBetween(asOf, first));
  }
  const durations = eps.filter((e) => e.resolved && e.resolvedAt).map((e) => hoursBetween(e.resolvedAt!, e.start));
  const accepted = eps.filter((e) => e.outcome === 'accepted').length;
  const overruled = eps.filter((e) => e.outcome === 'overruled').length;
  const decided = accepted + overruled;
  const settings = new Map<string, number>();
  for (const e of eps) {
    const key = JSON.stringify([e.address, e.attribute]);
    settings.set(key, (settings.get(key) ?? 0) + 1);
  }
  return {
    episodes: eps.length,
    managed,
    unmanaged,
    driftedResources: drifted,
    iacCoverage: managed === null ? null : pct(managed, managed + (unmanaged ?? 0)),
    driftRate: !managed ? null : pct(drifted, managed),
    openCount: open.length,
    oldestOpenHours: oldest,
    mttrHours: durations.length ? round1(durations.reduce((a, b) => a + b, 0) / durations.length) : null,
    decided,
    overruleRate: pct(overruled, decided),
    alertPrecision: pct(accepted, decided),
    recurringOffenders: [...settings.values()].filter((n) => n >= RECURRING_MIN).length,
  };
}

const csvCell = (value: unknown): string => {
  let text = value === null || value === undefined ? '' : String(value);
  if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`; // spreadsheets would run it as a formula
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
};

export function episodesCsv(rows: Episode[]): string {
  const lines = [CSV_COLUMNS.join(',')];
  for (const e of rows) {
    lines.push(CSV_COLUMNS.map((c) => csvCell((e as unknown as Record<string, unknown>)[c])).join(','));
  }
  return lines.join('\n') + '\n';
}

// ---- helpers for charts and tables (no Python twin) ----

export const dayOf = (iso: string): string => iso.slice(0, 10);

export function addDays(day: string, n: number): string {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

/** Every day from the first to the last episode (or the chosen range), zero where nothing happened. */
export function dailyBySeverity(eps: Episode[], f: Loose, asOf: string | null) {
  if (!eps.length) return [];
  const starts = eps.map((e) => dayOf(e.start)).sort();
  const first = f.from || starts[0];
  const last = f.to || (asOf ? dayOf(asOf) : starts[starts.length - 1]);
  const rows: Record<string, number | string>[] = [];
  const index = new Map<string, Record<string, number | string>>();
  for (let d = first, guard = 0; d <= last && guard < 800; d = addDays(d, 1), guard++) {
    const row = { day: d, critical: 0, high: 0, medium: 0, low: 0 };
    rows.push(row);
    index.set(d, row);
  }
  for (const e of eps) {
    const row = index.get(dayOf(e.start));
    if (row) row[e.severity] = ((row[e.severity] as number) ?? 0) + 1;
  }
  return rows;
}

export function countBy<T>(items: T[], key: (item: T) => string): [string, number][] {
  const m = new Map<string, number>();
  for (const i of items) m.set(key(i), (m.get(key(i)) ?? 0) + 1);
  return [...m.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

/** Monday of the week (UTC) a day falls in. */
export function weekStart(day: string): string {
  const dow = (new Date(`${day}T00:00:00Z`).getUTCDay() + 6) % 7;
  return addDays(day, -dow);
}

export function weeklyOverrule(eps: Episode[]) {
  const weeks = new Map<string, { accepted: number; overruled: number }>();
  for (const e of eps) {
    if (e.outcome !== 'accepted' && e.outcome !== 'overruled') continue;
    const w = weekStart(dayOf(e.start));
    const cell = weeks.get(w) ?? { accepted: 0, overruled: 0 };
    cell[e.outcome] += 1;
    weeks.set(w, cell);
  }
  return [...weeks.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([week, c]) => ({ week, rate: round1((100 * c.overruled) / (c.accepted + c.overruled)), decided: c.accepted + c.overruled }));
}

export interface Offender {
  address: string;
  attribute: string | null;
  count: number;
  team: string;
  lastSeen: string;
}

export function recurringOffenders(eps: Episode[]): Offender[] {
  const m = new Map<string, Offender>();
  for (const e of eps) {
    const key = JSON.stringify([e.address, e.attribute]);
    const cur = m.get(key);
    if (cur) {
      cur.count += 1;
      if (e.start > cur.lastSeen) cur.lastSeen = e.start;
    } else m.set(key, { address: e.address, attribute: e.attribute, count: 1, team: e.team, lastSeen: e.start });
  }
  return [...m.values()].filter((o) => o.count >= RECURRING_MIN).sort((a, b) => b.count - a.count || a.address.localeCompare(b.address));
}

export const episodeKey = (e: Episode): string => `${e.id}~${e.start}`;

export function distinct(episodes: Episode[], key: 'team' | 'repo' | 'environment' | 'driftType' | 'decidedBy' | 'outcome' | 'severity'): string[] {
  return [...new Set(episodes.map((e) => String(e[key])))].sort();
}

// ---- guardrails ----

export interface GuardrailSummary {
  neverSoften: Episode[];
  suspicious: Episode[];
  calls: number;
  invalid: number;
  peakCalls: number;
  peakRun: AuditRun | null;
  runsWithCalls: number;
  limit: number | null;
  runs: AuditRun[];
}

export function guardrailSummary(eps: Episode[], audit: AuditRun[], f: Loose, limit: number | null): GuardrailSummary {
  const runs = audit.filter(
    (r) => inRange(r.t, f) && (!f.repo || r.repo === f.repo) && (!f.environment || r.environment === f.environment) && (!f.driftType || r.driftType === f.driftType),
  );
  const peak = runs.reduce<AuditRun | null>((m, r) => (!m || r.calls > m.calls ? r : m), null);
  return {
    neverSoften: eps.filter((e) => e.guardrails?.includes('never-soften')),
    suspicious: eps.filter((e) => e.guardrails?.includes('suspicious-input')),
    calls: runs.reduce((a, r) => a + r.calls, 0),
    invalid: runs.reduce((a, r) => a + r.invalid, 0),
    peakCalls: peak?.calls ?? 0,
    peakRun: peak,
    runsWithCalls: runs.length,
    limit,
    runs,
  };
}
