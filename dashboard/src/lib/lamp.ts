// The status lamp in the header: how fresh the last scan is. The thresholds scale with the
// expected cadence (`dashboard.scan_every_hours`): green up to 1.5x, grey up to 3x, amber beyond.
import { ago } from './format';
import { DEFAULT_CADENCE_HOURS, LATE_FACTOR, ON_TIME_FACTOR, isSimulated } from './scans';

export type LampTone = 'fresh' | 'aging' | 'stale' | 'simulated';
export interface Lamp {
  tone: LampTone;
  label: string;
  /** True when the last scan is older than 3x the cadence: scans have probably stopped. */
  paused: boolean;
}

/**
 * `lastScan` is the time of the latest scan in the data. Data that says it is simulated is
 * always grey and says "Simulated", whatever its age.
 */
export function scanLamp(lastScan: string | null | undefined, note: string | null | undefined, now: Date, cadenceHours = DEFAULT_CADENCE_HOURS): Lamp {
  if (isSimulated(note)) return { tone: 'simulated', label: 'Simulated', paused: false };
  const t = lastScan ? Date.parse(lastScan) : NaN;
  if (Number.isNaN(t)) return { tone: 'stale', label: 'No scan time', paused: false };
  const hours = (now.getTime() - t) / 3_600_000;
  const stale = hours > LATE_FACTOR * cadenceHours;
  const tone: LampTone = hours <= ON_TIME_FACTOR * cadenceHours ? 'fresh' : stale ? 'stale' : 'aging';
  return { tone, label: `Last scan ${ago(new Date(t), now)}`, paused: stale };
}
