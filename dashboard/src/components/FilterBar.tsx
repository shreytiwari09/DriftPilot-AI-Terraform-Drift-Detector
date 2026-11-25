import { useEffect, useState } from 'react';
import { shortDate } from '../lib/format';
import { addDays, distinct } from '../lib/logic';
import { EMPTY_FILTERS } from '../lib/route';
import type { DashboardData, Filters } from '../types';
import { Icon } from './ui';

interface Props {
  data: DashboardData;
  filters: Filters;
  matches: number;
  onChange: (next: Filters) => void;
}

function Select({ id, label, value, options, onChange }: { id: string; label: string; value: string; options: string[]; onChange: (v: string) => void }) {
  return (
    <div>
      <label className="label" htmlFor={id}>{label}</label>
      <div className="relative">
        <select id={id} className="field" value={value} onChange={(e) => onChange(e.target.value)}>
          <option value="">All</option>
          {value && !options.includes(value) && <option value={value}>{value}</option>}
          {options.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
        <Icon name="chevron-down" className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-mute" />
      </div>
    </div>
  );
}

const SEVERITY_OPTIONS = ['critical', 'high', 'medium', 'low'];
const PRESETS: [number | null, string][] = [[7, '7 d'], [30, '30 d'], [90, '90 d'], [null, 'All']];

const LABELS: Partial<Record<keyof Filters, string>> = {
  from: 'From', to: 'To', team: 'Team', repo: 'Repo', environment: 'Environment', driftType: 'Drift type',
  severity: 'Severity', status: 'Status', decidedBy: 'Decided by', outcome: 'Outcome',
};
const PANEL_KEYS = Object.keys(LABELS) as (keyof Filters)[];

export default function FilterBar({ data, filters, matches, onChange }: Props) {
  const [panel, setPanel] = useState(false);
  const [search, setSearch] = useState(filters.search);
  useEffect(() => setSearch(filters.search), [filters.search]);
  useEffect(() => {
    if (search === filters.search) return;
    const t = window.setTimeout(() => onChange({ ...filters, search }), 250);
    return () => window.clearTimeout(t);
  }, [search]); // eslint-disable-line react-hooks/exhaustive-deps

  const set = (k: keyof Filters) => (v: string) => onChange({ ...filters, [k]: v });
  const eps = data.episodes;
  const last = data.asOf?.slice(0, 10) ?? new Date().toISOString().slice(0, 10);
  const preset = (days: number | null) => onChange({ ...filters, from: days ? addDays(last, -days) : '', to: '' });
  const presetOn = (days: number | null) => (days === null ? !filters.from && !filters.to : filters.from === addDays(last, -days) && !filters.to);
  const presetActive = PRESETS.some(([d]) => d !== null && presetOn(d));
  // The 7/30/90 d choice has its own control, so it is not counted or shown as a chip.
  const chips = PANEL_KEYS.filter((k) => filters[k] && !(k === 'from' && presetActive));
  const anyActive = chips.length > 0 || !!filters.search || presetActive;
  const chipText = (k: keyof Filters) => (k === 'from' || k === 'to' ? shortDate(filters[k]) : filters[k]);

  return (
    <section aria-label="Filters" className="mb-6">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-[320px]">
          <label htmlFor="f-search" className="sr-only">Search</label>
          <Icon name="search" className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-mute" />
          <input id="f-search" type="search" className="field !pl-9" placeholder="Search" aria-describedby="f-search-hint" value={search} onChange={(e) => setSearch(e.target.value)} />
          <span id="f-search-hint" className="sr-only">Searches resource, setting, team and repo</span>
        </div>
        <div role="group" aria-label="Quick date range" className="flex h-9 w-full gap-0.5 rounded-lg border border-line p-0.5 sm:w-auto">
          {PRESETS.map(([d, l]) => (
            <button key={l} type="button" aria-pressed={presetOn(d)} onClick={() => preset(d)}
              className={`h-full flex-1 rounded-md px-3 font-mono text-xs transition-colors sm:flex-none ${presetOn(d) ? 'bg-sunken text-brand-ink' : 'text-ink2 hover:bg-sunken hover:text-ink'}`}>{l}</button>
          ))}
        </div>
        <button type="button" className="btn" aria-expanded={panel} aria-controls="filter-panel" onClick={() => setPanel((o) => !o)}>
          <Icon name="filter" /> Filters
          {chips.length > 0 && <span className="fig rounded bg-brand/15 px-1.5 text-xs text-brand-ink" aria-label={`${chips.length} active`}>{chips.length}</span>}
        </button>
        {anyActive && <button type="button" className="btn btn-ghost" onClick={() => onChange({ ...EMPTY_FILTERS })}>Reset</button>}
        <span className="fig ml-auto text-xs text-mute" aria-live="polite">{matches.toLocaleString('en-US')} of {eps.length.toLocaleString('en-US')} episodes</span>
      </div>

      {chips.length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-2" aria-label="Active filters">
          {chips.map((k) => (
            <li key={k} className="flex h-7 items-center gap-1 rounded-md bg-sunken pl-2 text-xs text-ink2">
              <span>{LABELS[k]}:</span> <span className="fig text-ink">{chipText(k)}</span>
              <button type="button" className="grid h-7 w-7 place-items-center rounded-md text-mute transition-colors hover:text-ink" aria-label={`Remove filter ${LABELS[k]}: ${chipText(k)}`} onClick={() => set(k)('')}><Icon name="close" className="h-3.5 w-3.5" /></button>
            </li>
          ))}
        </ul>
      )}

      <div id="filter-panel" hidden={!panel} className="mt-3 rounded-2xl border border-line bg-surface p-4 sm:p-5">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-5">
          <div>
            <label className="label" htmlFor="f-from">From</label>
            <input id="f-from" type="date" className="field" value={filters.from} max={filters.to || undefined} onChange={(e) => set('from')(e.target.value)} />
          </div>
          <div>
            <label className="label" htmlFor="f-to">To</label>
            <input id="f-to" type="date" className="field" value={filters.to} min={filters.from || undefined} onChange={(e) => set('to')(e.target.value)} />
          </div>
          <Select id="f-team" label="Team" value={filters.team} options={distinct(eps, 'team')} onChange={set('team')} />
          <Select id="f-repo" label="Repo" value={filters.repo} options={distinct(eps, 'repo')} onChange={set('repo')} />
          <Select id="f-environment" label="Environment" value={filters.environment} options={distinct(eps, 'environment')} onChange={set('environment')} />
          <Select id="f-driftType" label="Drift type" value={filters.driftType} options={distinct(eps, 'driftType')} onChange={set('driftType')} />
          <Select id="f-severity" label="Severity" value={filters.severity} options={SEVERITY_OPTIONS} onChange={set('severity')} />
          <Select id="f-status" label="Status" value={filters.status} options={['open', 'resolved']} onChange={set('status')} />
          <Select id="f-decidedBy" label="Decided by" value={filters.decidedBy} options={distinct(eps, 'decidedBy')} onChange={set('decidedBy')} />
          <Select id="f-outcome" label="Human outcome" value={filters.outcome} options={['accepted', 'overruled', 'pending']} onChange={set('outcome')} />
        </div>
      </div>
    </section>
  );
}
