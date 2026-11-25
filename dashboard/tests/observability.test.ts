import { describe, expect, it } from 'vitest';
import fixture from './fixtures/sim.json';
import { computeKpis } from '../src/lib/logic';
import { cadenceOf, nextExpected, recentRuns, referenceNow, scanStatus, summarizeScans } from '../src/lib/scans';
import { ageHours, ageLabel, needsAttention, overdueHours, slaHoursFor } from '../src/lib/sla';
import { makeDelta, presetDays, previousWindow, trendDeltas } from '../src/lib/trend';
import type { DashboardData, Episode, Kpis } from '../src/types';

const data = fixture.data as unknown as DashboardData;
const windows = (fixture as unknown as { windowCases: { filters: Record<string, string>; window: { days: number; from: string; to: string } | null; kpis: Kpis | null }[] }).windowCases;

describe('scan status (on time <= 1.5x, late <= 3x, stale beyond)', () => {
  it('uses the cadence of 6 h', () => {
    expect(scanStatus(9, 6)).toBe('on_time');
    expect(scanStatus(9.1, 6)).toBe('late');
    expect(scanStatus(18, 6)).toBe('late');
    expect(scanStatus(18.1, 6)).toBe('stale');
  });
  it('scales with a 12 h cadence', () => {
    expect(scanStatus(18, 12)).toBe('on_time');
    expect(scanStatus(19, 12)).toBe('late');
    expect(scanStatus(36, 12)).toBe('late');
    expect(scanStatus(37, 12)).toBe('stale');
    expect(scanStatus(10, 1)).toBe('stale');
  });
  it('next expected scan is one cadence after the last', () => {
    expect(nextExpected('2026-11-25T06:00:00Z', 12).toISOString()).toBe('2026-11-25T18:00:00.000Z');
  });
});

describe('scan summary from the simulated data', () => {
  const now = new Date('2030-01-01T00:00:00Z'); // far later: simulated data must ignore the clock
  it('judges simulated data against its own latest scan', () => {
    expect(data.note).toBeNull(); // the fixture has no note: use a copy that says simulated
    const sim = { ...data, note: 'Simulated history' };
    expect(referenceNow(sim, now).toISOString()).toBe('2026-10-24T18:21:00.000Z');
    const s = summarizeScans(sim, now);
    expect(s.total).toBe(5);
    expect(s.rows.filter((r) => r.status === 'late').map((r) => r.repo)).toEqual(['driftpilot-demo/database']);
    expect(s.onTime).toBe(4);
    expect(s.rows[0].status).toBe('late'); // worst first
    expect(s.errors7d).toBeGreaterThan(0);
    expect(s.runs24h).toBeGreaterThan(10);
  });
  it('uses the real clock for real data, so everything is stale long after', () => {
    const s = summarizeScans(data, now);
    expect(s.rows.every((r) => r.status === 'stale')).toBe(true);
    expect(s.onTime).toBe(0);
  });
  it('a 12 h cadence turns the late stream on time', () => {
    const sim = { ...data, note: 'simulated', scans: { ...data.scans!, expectedHours: 12 } };
    expect(cadenceOf(sim)).toBe(12);
    expect(summarizeScans(sim, now).onTime).toBe(5);
  });
  it('filters streams and lists recent runs newest first', () => {
    const sim = { ...data, note: 'simulated' };
    expect(summarizeScans(sim, now, { driftType: 'database' }).total).toBe(1);
    const rows = recentRuns(summarizeScans(sim, now).rows, 10);
    expect(rows).toHaveLength(10);
    expect(rows.map((r) => r.t)).toEqual([...rows.map((r) => r.t)].sort().reverse());
  });
  it('copes with data that has no scan health (older data.json)', () => {
    const old = { ...data, scans: undefined };
    expect(summarizeScans(old, new Date()).total).toBe(0);
    expect(cadenceOf(old)).toBe(6);
  });
});

describe('SLA and aging', () => {
  const sla = { critical: 24, high: 72, medium: 168, low: null };
  const ep = (o: Partial<Episode>): Episode => ({ id: 'x', address: 'a.b', attribute: null, resourceType: 't', start: '2026-11-24T00:00:00Z', end: '', resolvedAt: null, runsSeen: 1, severity: 'high', category: 'c', action: 'revert', decidedBy: 'rule', outcome: 'pending', resolved: false, team: 't', repo: 'r', environment: 'e', account: 'a', driftType: 'infrastructure', ...o });
  it('reads the deadline per severity; low and unknown have none', () => {
    expect(slaHoursFor(sla, 'critical')).toBe(24);
    expect(slaHoursFor(sla, 'low')).toBeNull();
    expect(slaHoursFor(sla, 'none')).toBeNull();
    expect(slaHoursFor(undefined, 'critical')).toBeNull();
  });
  it('computes age from the episode start and the data time, and the overdue part', () => {
    expect(ageHours('2026-11-24T00:00:00Z', '2026-11-25T06:00:00Z')).toBe(30);
    expect(ageHours('2026-11-25T06:00:00Z', '2026-11-25T00:00:00Z')).toBe(0);
    expect(ageHours('2026-11-24T00:00:00Z', null)).toBeNull();
    expect(overdueHours(30, 24)).toBe(6);
    expect(overdueHours(24, 24)).toBe(0);
    expect(overdueHours(500, null)).toBe(0);
    expect(overdueHours(null, 24)).toBe(0);
  });
  it('labels ages in whole hours, then days', () => {
    expect(ageLabel(0.2)).toBe('<1 h');
    expect(ageLabel(30.4)).toBe('30 h');
    expect(ageLabel(47.6)).toBe('48 h');
    expect(ageLabel(72)).toBe('3 d');
  });
  it('sorts open episodes by severity, then oldest first, and skips resolved ones', () => {
    const rows = needsAttention(
      [ep({ address: 'a', severity: 'high', start: '2026-11-20T00:00:00Z' }), ep({ address: 'b', severity: 'critical', start: '2026-11-25T00:00:00Z' }), ep({ address: 'c', severity: 'high', start: '2026-11-10T00:00:00Z' }), ep({ address: 'd', resolved: true, severity: 'critical' }), ep({ address: 'e', severity: 'low' })],
      sla,
      '2026-11-25T06:00:00Z',
    );
    expect(rows.map((r) => r.episode.address)).toEqual(['b', 'c', 'a', 'e']);
    expect(rows[0].ageHours).toBe(6);
    expect(rows[0].overdueHours).toBe(0);
    expect(rows[1].overdueHours).toBe(15 * 24 + 6 - 72);
    expect(rows[3].overdueHours).toBe(0); // low has no deadline
  });
  it('works on the simulated data', () => {
    const open = needsAttention(data.episodes, data.sla, data.asOf);
    expect(open.length).toBe(data.kpis.openCount);
  });
});

describe('trend deltas', () => {
  it('formats a signed difference, neutral when equal', () => {
    expect(makeDelta(5, 3, '', 30)).toEqual({ text: '+2 vs previous 30 d', tone: 'worse', direction: 'up' });
    expect(makeDelta(20.5, 24.6, 'h', 7)).toEqual({ text: '-4.1 h vs previous 7 d', tone: 'better', direction: 'down' });
    expect(makeDelta(31.7, 28.5, 'pp', 90)?.text).toBe('+3.2 pp vs previous 90 d');
    expect(makeDelta(3, 3, '', 30)).toEqual({ text: 'No change vs previous 30 d', tone: 'same', direction: 'flat' });
    expect(makeDelta(null, 3, '', 30)).toBeNull();
    expect(makeDelta(3, null, '', 30)).toBeNull();
  });
  it('only treats 7/30/90 d presets as ranges with a previous window', () => {
    expect(presetDays({ from: '2026-09-24' }, data.asOf)).toBe(30);
    expect(presetDays({ from: '2026-09-23' }, data.asOf)).toBeNull();
    expect(presetDays({ from: '2026-09-24', to: '2026-10-01' }, data.asOf)).toBeNull();
    expect(presetDays({}, data.asOf)).toBeNull();
  });
  for (const c of windows) {
    it(`matches the Python window for ${JSON.stringify(c.filters)}`, () => {
      const w = previousWindow(c.filters, data.runs, data.asOf);
      expect(w).toEqual(c.window);
      if (!c.window || !c.kpis) return;
      const got = computeKpis(data.episodes, data.runs, { ...c.filters, from: c.window.from, to: c.window.to }, `${c.window.to}T23:59:59Z`);
      expect(got.openCount).toBe(c.kpis.openCount);
      expect(got.driftRate).toBe(c.kpis.driftRate);
      expect(got.mttrHours).toBe(c.kpis.mttrHours);
      const now = computeKpis(data.episodes, data.runs, c.filters, data.asOf);
      const d = trendDeltas(data.episodes, data.runs, c.filters, data.asOf, now);
      expect(d?.open?.text).toContain(`previous ${c.window.days} d`);
    });
  }
  it('has no deltas without a preset or when the data is too short', () => {
    const now = computeKpis(data.episodes, data.runs, {}, data.asOf);
    expect(trendDeltas(data.episodes, data.runs, {}, data.asOf, now)).toBeNull();
    expect(trendDeltas(data.episodes, data.runs, { from: '2026-07-26' }, data.asOf, now)).toBeNull();
  });
});
