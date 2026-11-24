import { useMemo, useState } from 'react';
import { shortDate } from '../lib/format';
import { episodeKey } from '../lib/logic';
import type { Episode } from '../types';
import { ExternalLink, Icon, SeverityBadge, Tag } from './ui';

type SortKey = 'start' | 'severity' | 'address' | 'team' | 'environment' | 'driftType' | 'status' | 'decidedBy' | 'outcome';
const SEV_RANK: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };

const COLS: { key: SortKey; label: string; className?: string }[] = [
  { key: 'severity', label: 'Severity' },
  { key: 'address', label: 'Resource' },
  { key: 'team', label: 'Team', className: 'hidden md:table-cell' },
  { key: 'environment', label: 'Env', className: 'hidden lg:table-cell' },
  { key: 'driftType', label: 'Type', className: 'hidden xl:table-cell' },
  { key: 'status', label: 'Status' },
  { key: 'decidedBy', label: 'Decided by', className: 'hidden lg:table-cell' },
  { key: 'outcome', label: 'Outcome', className: 'hidden xl:table-cell' },
  { key: 'start', label: 'First seen', className: 'hidden sm:table-cell' },
];

function value(e: Episode, k: SortKey): string | number {
  if (k === 'severity') return SEV_RANK[e.severity] ?? 9;
  if (k === 'status') return e.resolved ? 1 : 0;
  return (e[k] ?? '') as string;
}

const PAGE = 50;
const SECONDARY = new Set<SortKey>(['team', 'environment', 'driftType', 'decidedBy', 'outcome']);

export default function FindingsTable({ rows, onOpen, compact = false }: { rows: Episode[]; onOpen: (e: Episode) => void; compact?: boolean }) {
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: 'start', dir: -1 });
  const [shown, setShown] = useState(PAGE);
  const sorted = useMemo(
    () => [...rows].sort((a, b) => {
      const x = value(a, sort.key);
      const y = value(b, sort.key);
      const c = x < y ? -1 : x > y ? 1 : 0;
      return (c || (a.start < b.start ? 1 : -1)) * (c ? sort.dir : 1);
    }),
    [rows, sort],
  );
  const click = (key: SortKey) => setSort((s) => (s.key === key ? { key, dir: s.dir === 1 ? -1 : 1 } : { key, dir: key === 'start' ? -1 : 1 }));
  const visible = sorted.slice(0, compact ? 10 : shown);

  return (
    <div>
      <div className="scroll-x rounded-xl border border-line">
        <table className="w-full sm:min-w-[520px] border-collapse text-left text-sm">
          <caption className="sr-only">Drift episodes. Press Enter on a row to see details.</caption>
          <thead className="bg-sunken text-xs text-mute">
            <tr>
              {COLS.map((c) => (
                <th key={c.key} scope="col" className={`whitespace-nowrap px-3 py-2 font-semibold ${compact && SECONDARY.has(c.key) ? 'hidden' : (c.className ?? '')}`} aria-sort={sort.key === c.key ? (sort.dir === 1 ? 'ascending' : 'descending') : 'none'}>
                  <button type="button" onClick={() => click(c.key)} className="inline-flex items-center gap-1 rounded hover:text-ink">
                    {c.label}
                    {sort.key === c.key && <Icon name={sort.dir === 1 ? 'arrow-up' : 'arrow-down'} className="h-3 w-3" />}
                  </button>
                </th>
              ))}
              <th scope="col" className="hidden px-3 py-2 text-right font-semibold sm:table-cell">Links</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((e) => (
              <tr key={episodeKey(e)} tabIndex={0} onClick={() => onOpen(e)} onKeyDown={(ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); onOpen(e); } }}
                className="cursor-pointer border-t border-line transition hover:bg-sunken/70 focus-visible:bg-sunken">
                <td className="whitespace-nowrap px-3 py-2.5"><SeverityBadge severity={e.severity} /></td>
                <td className="max-w-[150px] px-3 py-2.5 sm:max-w-[260px]">
                  <div className="truncate font-mono text-xs font-medium" title={e.address}>{e.address}</div>
                  {e.attribute && <div className="truncate font-mono text-[11px] text-mute" title={e.attribute}>{e.attribute}</div>}
                </td>
                <td className={`px-3 py-2.5 ${compact ? 'hidden' : 'hidden md:table-cell'}`}>{e.team}</td>
                <td className={`px-3 py-2.5 ${compact ? 'hidden' : 'hidden lg:table-cell'}`}>{e.environment}</td>
                <td className={`px-3 py-2.5 ${compact ? 'hidden' : 'hidden xl:table-cell'}`}>{e.driftType}</td>
                <td className="px-3 py-2.5"><Tag tone={e.resolved ? 'ok' : 'warn'}>{e.resolved ? 'resolved' : 'open'}</Tag></td>
                <td className={`px-3 py-2.5 ${compact ? 'hidden' : 'hidden lg:table-cell'}`}>{e.decidedBy}</td>
                <td className={`px-3 py-2.5 ${compact ? 'hidden' : 'hidden xl:table-cell'}`}>{e.outcome}</td>
                <td className="hidden whitespace-nowrap px-3 py-2.5 text-mute sm:table-cell">{shortDate(e.start)}</td>
                <td className="hidden whitespace-nowrap px-3 py-2.5 text-right sm:table-cell" onClick={(ev) => ev.stopPropagation()} onKeyDown={(ev) => ev.stopPropagation()}>
                  <span className="inline-flex gap-1.5">
                    <ExternalLink href={e.issueUrl} className="btn !min-h-[28px] !px-2 text-xs" icon="external" hint="Opens the issue on GitHub in a new tab. GitHub asks you to log in; nothing changes until you act there.">Issue</ExternalLink>
                    <ExternalLink href={e.prUrl} className="btn !min-h-[28px] !px-2 text-xs" icon="external" hint="Opens the pull request on GitHub in a new tab. A person reviews and merges it.">PR</ExternalLink>
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!compact && rows.length > shown && (
        <div className="mt-3 flex items-center justify-between text-xs text-mute">
          <span>Showing {visible.length.toLocaleString('en-US')} of {rows.length.toLocaleString('en-US')}</span>
          <button type="button" className="btn text-xs" onClick={() => setShown((s) => s + 100)}>Show 100 more</button>
        </div>
      )}
    </div>
  );
}
