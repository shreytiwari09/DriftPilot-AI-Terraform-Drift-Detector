import { GroupedBars } from '../components/Charts';
import { Card, Empty, RankedBars, Tag } from '../components/ui';
import { hours, num, pct } from '../lib/format';
import { computeKpis, countBy, dailyBySeverity } from '../lib/logic';
import type { PageProps } from './shared';

const KINDS = [
  { key: 'infrastructure', title: 'Infrastructure drift', text: 'Terraform-managed cloud and repo settings (GitHub, Docker, AWS)' },
  { key: 'database', title: 'Database drift', text: 'Postgres schema changes that are not in the migration files' },
];

export default function Split({ data, filters, eps }: PageProps) {
  const base = { ...filters, driftType: '' };
  const daily = dailyBySeverity(eps, filters, data.asOf).map((r) => ({
    day: r.day,
    infrastructure: 0,
    database: 0,
  }));
  const index = new Map(daily.map((r) => [r.day, r]));
  for (const e of eps) {
    const row = index.get(e.start.slice(0, 10));
    if (row && (e.driftType === 'infrastructure' || e.driftType === 'database')) row[e.driftType] += 1;
  }
  const sev = KINDS.map((k) => {
    const segments: Record<string, number> = {};
    let value = 0;
    for (const e of eps) if (e.driftType === k.key) { segments[e.severity] = (segments[e.severity] ?? 0) + 1; value += 1; }
    return { name: k.key, value, segments };
  });

  return (
    <div className="stagger space-y-6">
      <div className="grid gap-6 lg:grid-cols-2">
        {KINDS.map((kind) => {
          const k = computeKpis(data.episodes, data.runs, { ...base, driftType: kind.key }, data.asOf);
          const types = countBy(eps.filter((e) => e.driftType === kind.key), (e) => e.resourceType).slice(0, 5);
          return (
            <Card key={kind.key} title={kind.title} subtitle={kind.text}>
              {k.episodes === 0 ? <Empty title={`No ${kind.key} drift in this view`} icon="check" /> : (
                <>
                  <dl className="grid grid-cols-2 gap-x-4 gap-y-4 sm:grid-cols-3">
                    {[['Episodes', num(k.episodes)], ['Open', num(k.openCount)], ['Drift rate', pct(k.driftRate)], ['IaC coverage', pct(k.iacCoverage)], ['Time to resolve', hours(k.mttrHours)], ['Overrule rate', pct(k.overruleRate)]].map(([l, v]) => (
                      <div key={l}><dt className="text-xs text-mute">{l}</dt><dd className="fig text-xl font-medium leading-7">{v}</dd></div>
                    ))}
                  </dl>
                  <h3 className="mb-2 mt-6 text-[13px] text-ink2">Most affected resource types</h3>
                  <div className="flex flex-wrap gap-2">{types.map(([t, n]) => <Tag key={t}>{t} · {n}</Tag>)}</div>
                </>
              )}
            </Card>
          );
        })}
      </div>
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
        <Card title="New episodes per day" subtitle="By drift type"
          action={<ul className="flex gap-4 text-xs text-ink2" aria-label="Legend"><li className="flex items-center gap-1.5"><span className="h-1.5 w-1.5 rounded-full bg-brand" aria-hidden="true" />Infrastructure</li><li className="flex items-center gap-1.5"><span className="h-1.5 w-1.5 rounded-full bg-ink/40" aria-hidden="true" />Database</li></ul>}>
          <GroupedBars rows={daily} label="Stacked bar chart of new episodes per day, infrastructure and database" keys={[{ key: 'infrastructure', name: 'Infrastructure', color: 'brand' }, { key: 'database', name: 'Database', color: 'neutral' }]} />
        </Card>
        <Card title="Severity mix" subtitle="Which kind of drift is more serious"><RankedBars rows={sev} label="Severity by drift type" /></Card>
      </div>
    </div>
  );
}
