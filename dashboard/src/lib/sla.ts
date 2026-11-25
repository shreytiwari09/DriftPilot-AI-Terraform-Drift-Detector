// How long open drift has waited, and whether it is past its deadline (`dashboard.sla_hours`).
// The maths is done here from the episode start and the data's own time, so it needs no extra
// data. The reference time is the latest scan in the data (what "open" was measured at).
import type { DashboardData, Episode, SlaHours } from '../types';

const HOUR = 3_600_000;
export const SEVERITY_RANK: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };

/** The data's own "now": the latest scan, else the time it was generated. */
export function dataTime(data: Pick<DashboardData, 'asOf' | 'generated'>): string | null {
  return data.asOf ?? data.generated ?? null;
}

/** The deadline in hours for a severity, or null when there is none. */
export function slaHoursFor(sla: SlaHours | undefined, severity: string): number | null {
  const v = sla?.[severity];
  return typeof v === 'number' && v > 0 ? v : null;
}

export function ageHours(startIso: string, nowIso: string | null): number | null {
  if (!nowIso) return null;
  const h = (Date.parse(nowIso) - Date.parse(startIso)) / HOUR;
  return Number.isNaN(h) ? null : Math.max(0, h);
}

/** Hours past the deadline, or 0 when within it (or when there is no deadline). */
export function overdueHours(age: number | null, slaHours: number | null): number {
  return age !== null && slaHours !== null && age > slaHours ? age - slaHours : 0;
}

/** "30 h", "3 d": whole units, to keep lists calm. */
export function ageLabel(hours: number): string {
  if (hours < 1) return '<1 h';
  return hours < 48 ? `${Math.round(hours)} h` : `${Math.round(hours / 24)} d`;
}

export interface Attention {
  episode: Episode;
  ageHours: number | null;
  overdueHours: number;
}

/** Open episodes, most serious first, then oldest first. */
export function needsAttention(eps: Episode[], sla: SlaHours | undefined, nowIso: string | null): Attention[] {
  return eps
    .filter((e) => !e.resolved)
    .map((episode) => {
      const age = ageHours(episode.start, nowIso);
      return { episode, ageHours: age, overdueHours: overdueHours(age, slaHoursFor(sla, episode.severity)) };
    })
    .sort(
      (a, b) =>
        (SEVERITY_RANK[a.episode.severity] ?? 9) - (SEVERITY_RANK[b.episode.severity] ?? 9) ||
        (b.ageHours ?? 0) - (a.ageHours ?? 0) ||
        a.episode.address.localeCompare(b.episode.address),
    );
}
