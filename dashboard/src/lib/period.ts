// The header's period text: "Last 90 days", "1 Oct to 24 Oct" or "All time".
import { shortDate } from './format';
import { addDays } from './logic';
import type { Filters } from '../types';

export function periodLabel(f: Pick<Filters, 'from' | 'to'>, asOf: string | null): string {
  const last = asOf?.slice(0, 10);
  if (f.from && !f.to && last) {
    for (const d of [7, 30, 90]) if (f.from === addDays(last, -d)) return `Last ${d} days`;
  }
  if (f.from && f.to) return `${shortDate(f.from)} to ${shortDate(f.to)}`;
  if (f.from) return `Since ${shortDate(f.from)}`;
  if (f.to) return `Until ${shortDate(f.to)}`;
  return 'All time';
}
