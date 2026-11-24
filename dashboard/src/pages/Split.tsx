import { GroupedBars, StackedHBars } from '../components/Charts';
import { Card, Empty, Tag } from '../components/ui';
import { hours, num, pct } from '../lib/format';
import { computeKpis, countBy, dailyBySeverity } from '../lib/logic';
import type { PageProps } from './shared';

const KINDS = [
  { key: 'infrastructure', title: 'Infrastructure drift', text: 'Terraform-managed cloud and repo settings (GitHub, Docker, AWS).' },
  { key: 'database', title: 'Database drift', text: 'Postgres schema changes that are not in the migration files.' },
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
    const row = { name: k.key, critical: 0, high: 0, medium: 0, low: 0 } as Record<string, number | string>;
    for (const e of eps) if (e.driftType === k.key) row[e.severity] = (Number(row[e.severity]) || 0) + 1;
    return row as { name: string; critical: number; high: number; medium: number; low: number };
  });

  return (
    <div className="space-y-5">
      <div><h2 className="h-page">Infrastructure vs Database</h2><p className="text-sm text-mute">One product, two kinds of drift. The same filters apply here, except the drift type, which this page splits for you.</p></div>
      <div className="grid gap-4 lg:grid-cols-2">
        {KINDS.map((kind) => {
          const k = computeKpis(data.episodes, data.runs, { ...base, driftType: kind.key }, data.asOf);
          const types = countBy(eps.filter((e) => e.driftType === kind.key), (e) => e.resourceType).slice(0, 5);
          return (
            <Card key={kind.key} title={kind.title} subtitle={kind.text}>
              {k.episodes === 0 ? <Empty title={`No ${kind.key} drift in this view`} icon="check" /> : (
                <>
                  <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                    {[['Episodes', num(k.episodes)], ['Open', num(k.openCount)], ['Drift rate', pct(k.driftRate)], ['IaC coverage', pct(k.iacCoverage)], ['Time to resolve', hours(k.mttrHours)], ['Overrule rate', pct(k.overruleRate)]].map(([l, v]) => (
                      <div key={l} className="rounded-xl bg-sunken p-3"><dt className="text-xs text-mute">{l}</dt><dd className="text-xl font-semibold tabular-nums">{v}</dd></div>
                    ))}
                  </dl>
                  <p className="mb-1 mt-4 text-xs font-semibold text-mute">Most affected resource types</p>
                  <div className="flex flex-wrap gap-1.5">{types.map(([t, n]) => <Tag key={t}>{t} · {n}</Tag>)}</div>
                </>
              )}
            </Card>
          );
        })}
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="New episodes per day" subtitle="By drift type"><GroupedBars rows={daily} label="Stacked bar chart of new episodes per day, infrastructure and database" keys={[{ key: 'infrastructure', name: 'Infrastructure', color: 'brand' }, { key: 'database', name: 'Database', color: 'teal' }]} /></Card>
        <Card title="Severity mix" subtitle="Which kind of drift is more serious"><StackedHBars rows={sev} label="Bar chart of severity by drift type" /></Card>
      </div>
    </div>
  );
}
