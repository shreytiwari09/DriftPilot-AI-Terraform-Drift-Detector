import { ago } from '../lib/format';
import { scanLamp } from '../lib/lamp';
import { cadenceOf, latestScan, referenceNow } from '../lib/scans';
import { ageLabel, dataTime, needsAttention } from '../lib/sla';
import type { DashboardData, Episode } from '../types';
import { Card, ExternalLink, LAMP_DOT, Tag } from './ui';

const SEV_DOT: Record<string, string> = { critical: 'bg-crit', high: 'bg-high', medium: 'bg-med', low: 'bg-low' };
const SHOWN = 5;
const LINK_BTN = 'btn btn-ghost h-8 w-8 px-0';

interface Props {
  data: DashboardData;
  eps: Episode[];
  now: Date;
  seeAllHref: string;
  onOpen: (e: Episode) => void;
}

/** What to look at first: open drift, most serious and oldest first, with its deadline. */
export default function NeedsAttention({ data, eps, now, seeAllHref, onOpen }: Props) {
  const items = needsAttention(eps, data.sla, dataTime(data));
  const last = latestScan(data);
  const lamp = scanLamp(last, data.note, now, cadenceOf(data));

  if (items.length === 0) {
    const since = last ? ago(new Date(last), referenceNow(data, now)) : null;
    return (
      <section aria-label="Needs attention" className="card flex min-h-12 items-center gap-3 px-4 py-3 sm:px-5" role="status">
        <span className={`h-2 w-2 shrink-0 rounded-full ${LAMP_DOT[lamp.tone]}`} aria-hidden="true" />
        <p className="text-sm">
          <span className="font-medium">Nothing open.</span> <span className="text-ink2">{since ? `Last scan ${since}` : 'No scan time in this data'}</span>
        </p>
      </section>
    );
  }

  return (
    <Card
      flush
      title="Needs attention"
      subtitle={`Open drift, most serious first${data.sla ? ', with its deadline' : ''}`}
      action={<a href={seeAllHref} className="btn btn-ghost btn-sm">{items.length > SHOWN ? `See all ${items.length}` : 'See all'}</a>}
    >
      <ul className="border-t border-line">
        {items.slice(0, SHOWN).map(({ episode: e, ageHours, overdueHours }) => (
          <li key={`${e.id}~${e.start}`} className="grid min-h-12 grid-cols-[1fr_auto] items-center gap-x-4 border-b border-line px-4 py-2 last:border-b-0 sm:px-5 md:grid-cols-[minmax(0,1fr)_auto_auto_auto]">
            <button type="button" onClick={() => onOpen(e)} className="flex min-w-0 items-center gap-3 rounded text-left transition-colors hover:text-brand-ink">
              <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${SEV_DOT[e.severity] ?? SEV_DOT.low}`} aria-hidden="true" />
              <span className="sr-only">{e.severity}: </span>
              <span className="min-w-0">
                <span className="block truncate font-mono text-xs" title={e.address}>{e.address}</span>
                {e.attribute && <span className="block truncate font-mono text-xs text-mute" title={e.attribute}>{e.attribute}</span>}
              </span>
            </button>
            <span className="fig hidden whitespace-nowrap text-xs md:block">
              {ageHours === null ? '' : <span className="text-ink2">{ageLabel(ageHours)} open</span>}
              {overdueHours > 0 && <span className="ml-2 text-crit">overdue by {ageLabel(overdueHours)}</span>}
            </span>
            <span className="hidden md:block"><Tag>{e.team}</Tag></span>
            <span className="inline-flex gap-1">
              {e.issueUrl ? <ExternalLink href={e.issueUrl} className={LINK_BTN} icon="issue" label="Open issue on GitHub" hint="Open issue: opens it on GitHub in a new tab. GitHub asks you to log in; nothing changes until you act there." /> : <span className="hidden h-8 w-8 sm:block" aria-hidden="true" />}
              {e.prUrl ? <ExternalLink href={e.prUrl} className={LINK_BTN} icon="pr" label="Open pull request on GitHub" hint="Open pull request: opens it on GitHub in a new tab. A person reviews and merges it." /> : <span className="hidden h-8 w-8 sm:block" aria-hidden="true" />}
            </span>
            <span className="fig col-span-2 mt-1 text-xs md:hidden">
              {ageHours !== null && <span className="text-ink2">{ageLabel(ageHours)} open</span>}
              {overdueHours > 0 && <span className="ml-2 text-crit">overdue by {ageLabel(overdueHours)}</span>}
              <span className="ml-2 text-mute">{e.team}</span>
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}
