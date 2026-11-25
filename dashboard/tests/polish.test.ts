import { describe, expect, it } from 'vitest';
import { ago } from '../src/lib/format';
import { scanLamp } from '../src/lib/lamp';
import { periodLabel } from '../src/lib/period';

const NOW = new Date('2026-11-25T12:00:00Z');
const hoursAgo = (h: number) => new Date(NOW.getTime() - h * 3_600_000).toISOString();

describe('status lamp', () => {
  it('is green up to 1.5x the cadence and says how long ago (cadence 6 h)', () => {
    expect(scanLamp(hoursAgo(2), null, NOW)).toEqual({ tone: 'fresh', label: 'Last scan 2 h ago', paused: false });
    expect(scanLamp(hoursAgo(9), null, NOW).tone).toBe('fresh');
  });
  it('is grey up to 3x and amber beyond, with a paused hint only past 3x (cadence 6 h)', () => {
    expect(scanLamp(hoursAgo(10), null, NOW)).toMatchObject({ tone: 'aging', paused: false });
    expect(scanLamp(hoursAgo(18), null, NOW).tone).toBe('aging');
    expect(scanLamp(hoursAgo(18.5), null, NOW)).toMatchObject({ tone: 'stale', paused: true });
    expect(scanLamp(hoursAgo(30), null, NOW).label).toBe('Last scan 30 h ago');
    expect(scanLamp(hoursAgo(72), null, NOW).label).toBe('Last scan 3 d ago');
  });
  it('scales with the cadence: a 12 h schedule is green to 18 h, grey to 36 h, amber after', () => {
    expect(scanLamp(hoursAgo(15), null, NOW, 12).tone).toBe('fresh');
    expect(scanLamp(hoursAgo(15), null, NOW, 6).tone).toBe('aging');
    expect(scanLamp(hoursAgo(18), null, NOW, 12).tone).toBe('fresh');
    expect(scanLamp(hoursAgo(20), null, NOW, 12)).toMatchObject({ tone: 'aging', paused: false });
    expect(scanLamp(hoursAgo(36), null, NOW, 12).tone).toBe('aging');
    expect(scanLamp(hoursAgo(37), null, NOW, 12)).toMatchObject({ tone: 'stale', paused: true });
  });
  it('is neutral and says Simulated when the data note says so, whatever the age', () => {
    expect(scanLamp(hoursAgo(1), 'Simulated 90-day history (seed 7), not real data.', NOW)).toEqual({ tone: 'simulated', label: 'Simulated', paused: false });
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
