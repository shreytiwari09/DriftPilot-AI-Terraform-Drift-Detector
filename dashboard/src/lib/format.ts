export const dash = '—';

export function pct(v: number | null | undefined): string {
  return v === null || v === undefined ? dash : `${v.toFixed(1)}%`;
}

export function num(v: number | null | undefined): string {
  return v === null || v === undefined ? dash : v.toLocaleString('en-US');
}

/** 5.2 h -> "5.2 h", 49 h -> "2.0 d". */
export function hours(v: number | null | undefined): string {
  if (v === null || v === undefined) return dash;
  return v >= 48 ? `${(v / 24).toFixed(1)} d` : `${v.toFixed(1)} h`;
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return dash;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return dash;
  return d.toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' }) + ' UTC';
}

export function shortDate(iso: string | null | undefined): string {
  if (!iso) return dash;
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso);
  return Number.isNaN(d.getTime()) ? dash : d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' });
}

export function ago(from: Date | null, now: Date): string {
  if (!from) return dash;
  const s = Math.max(0, Math.round((now.getTime() - from.getTime()) / 1000));
  if (s < 10) return 'just now';
  if (s < 60) return `${s} s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  return `${Math.round(s / 3600)} h ago`;
}
