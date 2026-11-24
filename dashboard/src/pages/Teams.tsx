import { useMemo } from 'react';
import { StackedHBars } from '../components/Charts';
import { Card, Empty, Tag } from '../components/ui';
import { hours, num, pct } from '../lib/format';
import { computeKpis, recurringOffenders } from '../lib/logic';
import type { PageProps } from './shared';

export default function Teams({ data, filters, eps }: PageProps) {
  const teams = useMemo(() => [...new Set(eps.map((e) => e.team))].sort(), [eps]);
  const rows = useMemo(
    () => teams.map((team) => {
      const f = { ...filters, team };
      const k = computeKpis(data.episodes, data.runs, f, data.asOf);
      const mine = eps.filter((e) => e.team === team);
      return { team, k, offenders: recurringOffenders(mine).length };
    }).sort((a, b) => b.k.episodes - a.k.episodes),
    [teams, filters, data, eps],
  );
  const chart = rows.map((r) => {
    const row = { name: r.team, critical: 0, high: 0, medium: 0, low: 0 } as Record<string, number | string>;
    for (const e of eps) if (e.team === r.team) row[e.severity] = (Number(row[e.severity]) || 0) + 1;
    return row as { name: string; critical: number; high: number; medium: number; low: number };
  });
  const top = recurringOffenders(eps).slice(0, 8);

  return (
    <div className="space-y-5">
      <div><h2 className="h-page">Teams</h2><p className="text-sm text-mute">Who owns the drift, how quickly it gets fixed, and who keeps seeing the same problem. Ownership comes from tags, <code className="font-mono">.driftpilot.yml</code> or CODEOWNERS.</p></div>
      {rows.length === 0 ? <div className="card"><Empty title="No teams to show">No episodes match these filters.</Empty></div> : (
        <>
          <Card title="Per team" subtitle="Drift rate and coverage use each team's own managed resources. A dash means the data does not say.">
            <div className="scroll-x rounded-xl border border-line">
              <table className="w-full min-w-[720px] border-collapse text-left text-sm">
                <thead className="bg-sunken text-xs text-mute">
                  <tr>{['Team', 'Episodes', 'Open', 'Drift rate', 'Mean time to resolve', 'Overrule rate', 'Repeat offenders'].map((h) => <th key={h} scope="col" className="whitespace-nowrap px-3 py-2 font-semibold">{h}</th>)}</tr>
                </thead>
                <tbody>
                  {rows.map(({ team, k, offenders }) => (
                    <tr key={team} className="border-t border-line">
                      <th scope="row" className="px-3 py-2.5 font-semibold">{team}</th>
                      <td className="px-3 py-2.5 tabular-nums">{num(k.episodes)}</td>
                      <td className="px-3 py-2.5 tabular-nums">{k.openCount ? <Tag tone="warn">{k.openCount}</Tag> : <Tag tone="ok">0</Tag>}</td>
                      <td className="px-3 py-2.5 tabular-nums">{pct(k.driftRate)}</td>
                      <td className="px-3 py-2.5 tabular-nums">{hours(k.mttrHours)}</td>
                      <td className="px-3 py-2.5 tabular-nums">{pct(k.overruleRate)} <span className="text-xs text-mute">of {k.decided}</span></td>
                      <td className="px-3 py-2.5 tabular-nums">{offenders ? <Tag tone="warn">{offenders}</Tag> : 0}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <div className="grid gap-4 xl:grid-cols-2">
            <Card title="Episodes by team" subtitle="Stacked by severity"><StackedHBars rows={chart} label="Bar chart of drift episodes per team by severity" /></Card>
            <Card title="Repeat offenders" subtitle="Settings that keep drifting (3+ episodes)">
              {top.length ? (
                <ul className="divide-y divide-line">
                  {top.map((o) => (
                    <li key={`${o.address}${o.attribute}`} className="flex items-center justify-between gap-3 py-2.5">
                      <div className="min-w-0"><p className="truncate font-mono text-xs font-medium">{o.address}</p><p className="truncate text-xs text-mute">{o.attribute ?? ''} · team {o.team}</p></div>
                      <Tag tone="warn">{o.count} times</Tag>
                    </li>
                  ))}
                </ul>
              ) : <Empty title="No repeat offenders" icon="check">Nothing drifted three or more times in this view.</Empty>}
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
