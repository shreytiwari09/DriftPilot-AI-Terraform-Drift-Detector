import { describe, expect, it } from 'vitest';
import { ago } from '../src/lib/format';
import { scanLamp } from '../src/lib/lamp';
import { periodLabel } from '../src/lib/period';

const NOW = new Date('2026-11-25T12:00:00Z');
const hoursAgo = (h: number) => new Date(NOW.getTime() - h * 3_600_000).toISOString();

describe('status lamp', () => {
  it('is green up to 8 hours and says how long ago', () => {
    expect(scanLamp(hoursAgo(2), null, NOW)).toEqual({ tone: 'fresh', label: 'Checked 2 h ago' });
    expect(scanLamp(hoursAgo(8), null, NOW).tone).toBe('fresh');
  });
  it('is grey between 8 and 12 hours and amber after 12', () => {
    expect(scanLamp(hoursAgo(10), null, NOW).tone).toBe('aging');
    expect(scanLamp(hoursAgo(12.5), null, NOW).tone).toBe('stale');
    expect(scanLamp(hoursAgo(30), null, NOW).label).toBe('Checked 30 h ago');
    expect(scanLamp(hoursAgo(72), null, NOW).label).toBe('Checked 3 d ago');
  });
  it('is neutral and says Simulated when the data note says so, whatever the age', () => {
    expect(scanLamp(hoursAgo(1), 'Simulated 90-day history (seed 7), not real data.', NOW)).toEqual({ tone: 'simulated', label: 'Simulated' });
    expect(scanLamp(hoursAgo(500), 'simulated', NOW).tone).toBe('simulated');
  });
  it('does not pretend when there is no scan time', () => {
    expect(scanLamp(null, null, NOW).tone).toBe('stale');
    expect(scanLamp('not a date', null, NOW).label).toBe('No scan time');
  });
  it('ago switches to days after two days', () => {
    expect(ago(new Date(hoursAgo(47)), NOW)).toBe('47 h ago');
    expect(ago(new Date(hoursAgo(49)), NOW)).toBe('2 d ago');
  });
});

describe('period label', () => {
  it('names the quick ranges, custom ranges and all time', () => {
    expect(periodLabel({ from: '2026-10-17', to: '' }, '2026-10-24T18:21:00Z')).toBe('Last 7 days');
    expect(periodLabel({ from: '2026-07-26', to: '' }, '2026-10-24T18:21:00Z')).toBe('Last 90 days');
    expect(periodLabel({ from: '2026-10-01', to: '2026-10-10' }, null)).toBe('1 Oct to 10 Oct');
    expect(periodLabel({ from: '2026-10-01', to: '' }, null)).toBe('Since 1 Oct');
    expect(periodLabel({ from: '', to: '2026-10-10' }, null)).toBe('Until 10 Oct');
    expect(periodLabel({ from: '', to: '' }, null)).toBe('All time');
  });
});
