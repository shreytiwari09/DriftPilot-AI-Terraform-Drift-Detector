import { describe, expect, it } from 'vitest';
import { actionLinks, safeGithubUrl } from '../src/lib/url';
import { buildHash, parseHash } from '../src/lib/route';
import { addDays, dailyBySeverity, guardrailSummary, recurringOffenders, weekStart, weeklyOverrule } from '../src/lib/logic';
import { isData } from '../src/lib/useData';
import type { Episode } from '../src/types';

const ep = (o: Partial<Episode> = {}): Episode => ({
  id: 'f', address: 't.a', attribute: 'x', resourceType: 't', start: '2026-10-05T06:00:00Z', end: '2026-10-05T06:00:00Z',
  resolvedAt: null, runsSeen: 1, severity: 'high', category: 'security', action: 'revert', decidedBy: 'llm',
  outcome: 'accepted', resolved: false, team: 'platform', repo: 'acme/infra', environment: 'prod', account: 'unknown',
  driftType: 'infrastructure', ...o,
});

describe('links: only plain github.com URLs survive', () => {
  it('keeps real GitHub links', () => {
    expect(safeGithubUrl('https://github.com/acme/infra/pull/7')).toBe('https://github.com/acme/infra/pull/7');
  });
  it.each([
    'javascript:alert(1)', 'data:text/html,<script>1</script>', 'http://github.com/a/b', 'https://github.com.evil.io/a',
    'https://evil.io/github.com/a', 'https://u:p@github.com/a', 'https://github.com:8443/a', 'https://github.com/a"onmouseover=x',
    'https://github.com/a b', '//github.com/a', '', null, undefined, 42,
  ])('drops %s', (bad) => {
    expect(safeGithubUrl(bad)).toBeNull();
  });
  it('builds the three action links from repo, workflow and branch', () => {
    const l = actionLinks({ repo: 'acme/infra', workflow: 'driftpilot.yml', branch: 'main' });
    expect(l.scan).toBe('https://github.com/acme/infra/actions/workflows/driftpilot.yml');
    expect(l.settings).toBe('https://github.com/acme/infra/edit/main/.driftpilot.yml');
    expect(l.source).toBe('https://github.com/acme/infra');
  });
  it('hides a button when its piece is unknown or invalid', () => {
    expect(actionLinks(undefined)).toEqual({ scan: null, settings: null, source: null });
    const l = actionLinks({ repo: 'acme/infra', workflow: 'x y.yml', branch: 'a..b' });
    expect(l.scan).toBeNull();
    expect(l.settings).toBeNull();
    expect(l.source).not.toBeNull();
    expect(actionLinks({ repo: 'javascript:alert(1)//x', workflow: 'a.yml', branch: 'main' }).source).toBeNull();
  });
  it('uses the repo chosen in the filter bar when it is valid', () => {
    expect(actionLinks({ repo: 'a/b', workflow: 'w.yml', branch: 'main' }, 'c/d').source).toBe('https://github.com/c/d');
    expect(actionLinks({ repo: 'a/b', workflow: 'w.yml', branch: 'main' }, 'bad repo').source).toBe('https://github.com/a/b');
  });
});

describe('hash routing keeps filters in the URL', () => {
  it('round-trips a shared view', () => {
    const route = { page: 'findings' as const, filters: { ...parseHash('').filters, team: 'payments', severity: 'critical', search: 'a b&c' }, open: 'id~2026-10-01T06:00:00Z' };
    expect(parseHash(buildHash(route))).toEqual(route);
  });
  it('falls back to the overview for unknown pages', () => {
    expect(parseHash('#/nope?team=x')).toMatchObject({ page: 'overview', filters: { team: 'x' } });
    expect(parseHash('').page).toBe('overview');
  });
});

describe('chart helpers', () => {
  it('fills days without drift with zeros', () => {
    const rows = dailyBySeverity([ep({ start: '2026-10-01T01:00:00Z' }), ep({ start: '2026-10-04T01:00:00Z', severity: 'critical' })], {}, null);
    expect(rows.map((r) => r.day)).toEqual(['2026-10-01', '2026-10-02', '2026-10-03', '2026-10-04']);
    expect(rows[3].critical).toBe(1);
    expect(rows[1].high).toBe(0);
  });
  it('weeks start on Monday', () => {
    expect(weekStart('2026-10-25')).toBe('2026-10-19');
    expect(addDays('2026-10-31', 1)).toBe('2026-11-01');
  });
  it('computes the weekly overrule share', () => {
    const rows = weeklyOverrule([ep({ outcome: 'overruled' }), ep({ outcome: 'accepted' }), ep({ outcome: 'pending' })]);
    expect(rows).toEqual([{ week: '2026-10-05', rate: 50, decided: 2 }]);
  });
  it('lists settings with 3+ episodes', () => {
    const eps = [ep(), ep(), ep(), ep({ address: 't.b' })];
    expect(recurringOffenders(eps).map((o) => [o.address, o.count])).toEqual([['t.a', 3]]);
  });
});

describe('guardrails', () => {
  it('counts overrides, calls and the peak against the budget', () => {
    const eps = [ep({ guardrails: ['never-soften'] }), ep({ guardrails: ['suspicious-input'] }), ep()];
    const audit = [
      { runId: 'r1', t: '2026-10-05T00:00:00Z', repo: 'acme/infra', environment: 'prod', driftType: 'infrastructure', calls: 2, invalid: 1, events: {} },
      { runId: 'r2', t: '2026-10-06T00:00:00Z', repo: 'acme/db', environment: 'prod', driftType: 'database', calls: 5, invalid: 0, events: {} },
    ];
    const s = guardrailSummary(eps, audit, { repo: 'acme/infra' }, 60);
    expect([s.neverSoften.length, s.suspicious.length, s.calls, s.invalid, s.peakCalls, s.limit]).toEqual([1, 1, 2, 1, 2, 60]);
  });
});

describe('data loading', () => {
  it('recognises a data.json and rejects anything else', () => {
    expect(isData({ episodes: [], runs: [], kpis: {} })).toBe(true);
    expect(isData({ episodes: 'x' })).toBe(false);
    expect(isData(null)).toBe(false);
  });
});
