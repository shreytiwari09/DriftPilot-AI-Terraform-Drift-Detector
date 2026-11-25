// Hash routing: `#/findings?team=payments&severity=high&open=<id>`. The hash never reaches the
// server, so the app works from any GitHub Pages sub-path and from file://. Filters live in the
// query part, so copying the address bar shares the exact view.
import { useCallback, useEffect, useState } from 'react';
import { FILTER_KEYS, type Filters } from '../types';

export const PAGES = ['overview', 'findings', 'teams', 'split', 'scans', 'guardrails', 'about'] as const;
export type Page = (typeof PAGES)[number];

export interface Route {
  page: Page;
  filters: Filters;
  open: string;
}

export const EMPTY_FILTERS: Filters = {
  from: '', to: '', team: '', repo: '', environment: '', driftType: '', severity: '', status: '',
  decidedBy: '', outcome: '', search: '',
};

export function parseHash(hash: string): Route {
  const raw = hash.replace(/^#\/?/, '');
  const [path, query = ''] = raw.split('?');
  const page = (PAGES as readonly string[]).includes(path) ? (path as Page) : 'overview';
  const params = new URLSearchParams(query);
  const filters = { ...EMPTY_FILTERS };
  for (const k of FILTER_KEYS) filters[k] = (params.get(k) ?? '').slice(0, 200);
  return { page, filters, open: (params.get('open') ?? '').slice(0, 300) };
}

export function buildHash(route: Route): string {
  const params = new URLSearchParams();
  for (const k of FILTER_KEYS) if (route.filters[k]) params.set(k, route.filters[k]);
  if (route.open) params.set('open', route.open);
  const q = params.toString();
  return `#/${route.page}${q ? `?${q}` : ''}`;
}

export function useRoute() {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parseHash(window.location.hash));
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);
  const go = useCallback((next: Partial<Route>, replace = false) => {
    const merged = { ...parseHash(window.location.hash), ...next };
    const hash = buildHash(merged);
    if (hash === window.location.hash) return;
    if (replace) window.history.replaceState(null, '', hash);
    else window.history.pushState(null, '', hash);
    setRoute(merged);
  }, []);
  return { route, go };
}
