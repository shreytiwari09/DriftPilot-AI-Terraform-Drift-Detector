// "Compared with the previous period": when a 7, 30 or 90 day range is chosen, the previous
// window of the same length is computed with the same KPI maths. previous_window() in
// driftpilot/report/dashboard/data.py is the Python twin (tests/parity.test.ts compares them).
import type { Filters, Kpis, RunRow } from '../types';
import { addDays, computeKpis } from './logic';
import type { Episode } from '../types';

export const PRESET_DAYS = [7, 30, 90] as const;
type Loose = Partial<Record<keyof Filters, string | undefined>>;

/** Days in the active 7/30/90 d preset (from = latest scan day minus N, no end date), else null. */
export function presetDays(f: Loose, asOf: string | null): number | null {
  const last = asOf?.slice(0, 10);
  if (!f.from || f.to || !last) return null;
  return PRESET_DAYS.find((d) => f.from === addDays(last, -d)) ?? null;
}

export interface Window {
  days: number;
  from: string;
  to: string;
}

/**
 * The window of equal length just before the chosen one, or null when no preset is active or the
 * data does not reach back that far (a delta against a half-empty window would be misleading).
 */
export function previousWindow(f: Loose, runs: Pick<RunRow, 't'>[], asOf: string | null): Window | null {
  const days = presetDays(f, asOf);
  if (days === null || !f.from || runs.length === 0) return null;
  const from = addDays(f.from, -days);
  const first = runs.reduce((m, r) => (r.t < m ? r.t : m), runs[0].t).slice(0, 10);
  return from >= first ? { days, from, to: addDays(f.from, -1) } : null;
}

export type Tone = 'worse' | 'better' | 'same';
export interface Delta {
  text: string;
  tone: Tone;
  direction: 'up' | 'down' | 'flat';
}

const round1 = (x: number) => Math.round(x * 10) / 10;

/** A difference with a sign: "+2", "-4.1 h", "+3.2 pp". For all three figures, lower is better. */
export function makeDelta(current: number | null, previous: number | null, unit: '' | 'h' | 'pp', days: number): Delta | null {
  if (current === null || previous === null) return null;
  const diff = round1(current - previous);
  const suffix = unit ? ` ${unit}` : '';
  const text = `${diff > 0 ? '+' : diff < 0 ? '-' : ''}${Math.abs(diff)}${suffix} vs previous ${days} d`;
  if (diff === 0) return { text: `No change vs previous ${days} d`, tone: 'same', direction: 'flat' };
  return { text, tone: diff > 0 ? 'worse' : 'better', direction: diff > 0 ? 'up' : 'down' };
}

export interface Deltas {
  open: Delta | null;
  driftRate: Delta | null;
  mttr: Delta | null;
}

export function trendDeltas(episodes: Episode[], runs: RunRow[], f: Loose, asOf: string | null, current: Kpis): Deltas | null {
  const w = previousWindow(f, runs, asOf);
  if (!w) return null;
  const prev = computeKpis(episodes, runs, { ...f, from: w.from, to: w.to }, `${w.to}T23:59:59Z`);
  return {
    open: makeDelta(current.openCount, prev.openCount, '', w.days),
    driftRate: makeDelta(current.driftRate, prev.driftRate, 'pp', w.days),
    mttr: makeDelta(current.mttrHours, prev.mttrHours, 'h', w.days),
  };
}
