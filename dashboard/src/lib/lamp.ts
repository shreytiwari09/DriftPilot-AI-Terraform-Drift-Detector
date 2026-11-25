// The status lamp in the header: how fresh the last scan is, from the real `generated` time.
import { ago } from './format';

export type LampTone = 'fresh' | 'aging' | 'stale' | 'simulated';
export interface Lamp {
  tone: LampTone;
  label: string;
}

export const FRESH_HOURS = 8;
export const STALE_HOURS = 12;

/**
 * Green up to 8 h, grey between 8 and 12 h (not fresh, not yet worrying), amber after 12 h.
 * Data that says it is simulated is always grey and says "Simulated", whatever its age.
 */
export function scanLamp(generated: string | null | undefined, note: string | null | undefined, now: Date): Lamp {
  if (note && /simulated/i.test(note)) return { tone: 'simulated', label: 'Simulated' };
  const t = generated ? Date.parse(generated) : NaN;
  if (Number.isNaN(t)) return { tone: 'stale', label: 'No scan time' };
  const hours = (now.getTime() - t) / 3_600_000;
  const tone: LampTone = hours <= FRESH_HOURS ? 'fresh' : hours > STALE_HOURS ? 'stale' : 'aging';
  return { tone, label: `Checked ${ago(new Date(t), now)}` };
}
