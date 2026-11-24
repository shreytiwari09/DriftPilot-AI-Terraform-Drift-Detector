import { useEffect, useState } from 'react';
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
      <select id={id} className="field" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">All</option>
        {value && !options.includes(value) && <option value={value}>{value}</option>}
        {options.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    </div>
  );
}

const SEVERITY_OPTIONS = ['critical', 'high', 'medium', 'low'];

export default function FilterBar({ data, filters, matches, onChange }: Props) {
  const [openMobile, setOpenMobile] = useState(false);
  const [search, setSearch] = useState(filters.search);
  useEffect(() => setSearch(filters.search), [filters.search]);
  useEffect(() => {
    if (search === filters.search) return;
    const t = window.setTimeout(() => onChange({ ...filters, search }), 250);
    return () => window.clearTimeout(t);
  }, [search]); // eslint-disable-line react-hooks/exhaustive-deps

  const set = (k: keyof Filters) => (v: string) => onChange({ ...filters, [k]: v });
  const active = Object.values(filters).filter(Boolean).length;
  const eps = data.episodes;
  const last = data.asOf?.slice(0, 10) ?? new Date().toISOString().slice(0, 10);
  const preset = (days: number | null) => onChange({ ...filters, from: days ? addDays(last, -days) : '', to: '' });
  const presetOn = (days: number | null) => (days === null ? !filters.from && !filters.to : filters.from === addDays(last, -days) && !filters.to);

  return (
    <section aria-label="Filters" className="card mb-5 p-3 sm:p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button type="button" className="btn md:hidden" aria-expanded={openMobile} aria-controls="filter-fields" onClick={() => setOpenMobile((o) => !o)}>
          <Icon name="filter" /> Filters{active ? ` (${active})` : ''}
        </button>
        <div className="hidden items-center gap-2 text-sm font-semibold md:flex"><Icon name="filter" className="h-4 w-4 text-brand" /> Filters</div>
        <div className="flex flex-wrap items-center gap-2">
          <div role="group" aria-label="Quick date range" className="flex overflow-hidden rounded-lg border border-line text-xs">
            {[[7, 'Last 7 d'], [30, '30 d'], [90, '90 d'], [null, 'All']].map(([d, l]) => (
              <button key={String(l)} type="button" aria-pressed={presetOn(d as number | null)} onClick={() => preset(d as number | null)}
                className={`px-2.5 py-1.5 font-medium transition ${presetOn(d as number | null) ? 'bg-brand text-white dark:text-[#06101f]' : 'bg-surface text-mute hover:bg-sunken'}`}>{l}</button>
            ))}
          </div>
          <span className="text-xs text-mute" aria-live="polite">{matches.toLocaleString('en-US')} of {eps.length.toLocaleString('en-US')} episodes</span>
          <button type="button" className="btn !min-h-[30px] text-xs" disabled={!active} onClick={() => onChange({ ...EMPTY_FILTERS })}>Reset</button>
        </div>
      </div>
      <div id="filter-fields" className={`${openMobile ? 'grid' : 'hidden'} mt-3 grid-cols-2 gap-2.5 md:grid md:grid-cols-4 xl:grid-cols-6`}>
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
        <div className="col-span-2 md:col-span-2">
          <label className="label" htmlFor="f-search">Search</label>
          <div className="relative">
            <Icon name="search" className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-mute" />
            <input id="f-search" type="search" className="field !pl-8" placeholder="resource, setting, team, repo" value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
        </div>
      </div>
    </section>
  );
}
