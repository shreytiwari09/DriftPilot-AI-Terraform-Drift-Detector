// Loads data.json when the page opens and again every 5 minutes. If the fetch fails (for
// example when the page is opened from disk) the copy embedded in index.html is used.
import { useCallback, useEffect, useRef, useState } from 'react';
import type { DashboardData } from '../types';

export const REFRESH_MS = 5 * 60 * 1000;

export type Status = 'loading' | 'ready' | 'error';

export interface DataState {
  data: DashboardData | null;
  status: Status;
  source: 'fetched' | 'embedded' | null;
  checkedAt: Date | null;
  refreshError: string | null;
  refresh: () => void;
}

function embedded(): DashboardData | null {
  try {
    const text = document.getElementById('embedded-data')?.textContent ?? '';
    const parsed = JSON.parse(text);
    return isData(parsed) ? parsed : null;
  } catch {
    return null; // the placeholder in `npm run dev`, or an empty file
  }
}

export function isData(value: unknown): value is DashboardData {
  const d = value as DashboardData | null;
  return !!d && typeof d === 'object' && Array.isArray(d.episodes) && Array.isArray(d.runs) && typeof d.kpis === 'object';
}

export function useData(): DataState {
  const [data, setData] = useState<DashboardData | null>(null);
  const [status, setStatus] = useState<Status>('loading');
  const [source, setSource] = useState<'fetched' | 'embedded' | null>(null);
  const [checkedAt, setCheckedAt] = useState<Date | null>(null);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const have = useRef(false);

  const load = useCallback(async () => {
    try {
      const res = await fetch(`data.json?ts=${Date.now()}`, { cache: 'no-store' });
      if (!res.ok) throw new Error(`data.json answered ${res.status}`);
      const json: unknown = await res.json();
      if (!isData(json)) throw new Error('data.json is not in the expected format');
      setData(json);
      setSource('fetched');
      setStatus('ready');
      setRefreshError(null);
      have.current = true;
    } catch (err) {
      const copy = have.current ? null : embedded();
      if (copy) {
        setData(copy);
        setSource('embedded');
        setStatus('ready');
        have.current = true;
      } else if (!have.current) {
        setStatus('error');
      }
      setRefreshError(err instanceof Error ? err.message : String(err));
    } finally {
      setCheckedAt(new Date());
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [load]);

  return { data, status, source, checkedAt, refreshError, refresh: () => void load() };
}
