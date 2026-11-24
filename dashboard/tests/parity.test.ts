// The browser's numbers must equal the Python reference (driftpilot/report/dashboard/data.py)
// for the simulated history. The fixture is made by scripts/make_fixture.py; a Python test
// checks it is up to date.
import { describe, expect, it } from 'vitest';
import fixture from './fixtures/sim.json';
import { computeKpis, episodesCsv, filterEpisodes } from '../src/lib/logic';
import type { DashboardData, Episode, Kpis } from '../src/types';

const data = fixture.data as unknown as DashboardData;
const cases = fixture.cases as unknown as { filters: Record<string, string>; kpis: Kpis }[];

describe('KPI parity with Python compute_kpis', () => {
  it('has a real fixture to compare against', () => {
    expect(data.episodes.length).toBeGreaterThan(100);
    expect(cases.length).toBeGreaterThan(10);
    expect(new Set(data.episodes.map((e) => e.team)).size).toBeGreaterThan(3);
  });

  for (const c of cases) {
    it(`matches for ${JSON.stringify(c.filters)}`, () => {
      const got = computeKpis(data.episodes, data.runs, c.filters, data.asOf);
      expect(Object.keys(got).sort()).toEqual(Object.keys(c.kpis).sort());
      for (const key of Object.keys(c.kpis) as (keyof Kpis)[]) {
        const want = c.kpis[key];
        if (want === null || got[key] === null) expect(got[key], key).toBe(want);
        else expect(got[key] as number, key).toBeCloseTo(want, 1);
      }
    });
  }

  it('filters leave exactly the episodes Python counted', () => {
    for (const c of cases) {
      expect(filterEpisodes(data.episodes, c.filters).length).toBe(c.kpis.episodes);
    }
  });

  it('covers the per-team denominators (team filter)', () => {
    const withTeam = cases.filter((c) => c.filters.team && c.kpis.managed !== null);
    expect(withTeam.length).toBeGreaterThan(0);
  });
});

describe('CSV parity with Python episodes_csv', () => {
  it('writes the same text, including quoting and formula guards', () => {
    expect(episodesCsv(fixture.csvRows as unknown as Episode[])).toBe(fixture.csv);
  });
});
