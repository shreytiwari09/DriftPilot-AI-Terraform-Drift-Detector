import { useMemo } from 'react';
import { Card, Empty, RankedBars, StatusText } from '../components/ui';
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
    const segments: Record<string, number> = {};
    let value = 0;
    for (const e of eps) if (e.team === r.team) { segments[e.severity] = (segments[e.severity] ?? 0) + 1; value += 1; }
    return { name: r.team, value, segments };
  });
  const top = recurringOffenders(eps).slice(0, 8);

  return (
    <div className="stagger space-y-6">
      {rows.length === 0 ? <div className="card"><Empty title="No teams to show">No episodes match these filters.</Empty></div> : (
        <>
          <Card flush title="Per team" subtitle="Who owns the drift comes from tags, .driftpilot.yml or CODEOWNERS. Drift rate and coverage use each team's own managed resources; a dash means the data does not say">
            <div className="scroll-x">
              <table className="w-full min-w-[720px] border-collapse text-left text-sm">
                <thead className="text-xs text-mute">
                  <tr className="h-10 border-y border-line">{['Team', 'Episodes', 'Open', 'Drift rate', 'Mean time to resolve', 'Overrule rate', 'Repeat offenders'].map((h, i) => <th key={h} scope="col" className={`whitespace-nowrap px-4 font-normal first:pl-5 last:pr-5 ${i > 0 ? 'text-right' : ''}`}>{h}</th>)}</tr>
                </thead>
                <tbody>
                  {rows.map(({ team, k, offenders }) => (
                    <tr key={team} className="h-12 border-b border-line last:border-b-0">
                      <th scope="row" className="px-4 font-medium first:pl-5">{team}</th>
                      <td className="fig px-4 text-right">{num(k.episodes)}</td>
                      <td className="px-4 text-right"><StatusText dot={k.openCount ? 'bg-med' : 'bg-ok'}><span className="fig">{k.openCount}</span></StatusText></td>
                      <td className="fig px-4 text-right">{pct(k.driftRate)}</td>
                      <td className="fig px-4 text-right">{hours(k.mttrHours)}</td>
                      <td className="fig px-4 text-right">{pct(k.overruleRate)} <span className="text-xs text-mute">of {k.decided}</span></td>
                      <td className={`fig px-4 text-right last:pr-5 ${offenders ? '' : 'text-mute'}`}>{offenders}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <div className="grid gap-6 xl:grid-cols-2">
            <Card title="Episodes by team" subtitle="By severity"><RankedBars rows={chart} label="Drift episodes per team by severity" /></Card>
            <Card title="Repeat offenders" subtitle="Settings that keep drifting (3+ episodes)">
              {top.length ? (
                <ul className="divide-y divide-line">
                  {top.map((o) => (
                    <li key={`${o.address}${o.attribute}`} className="flex min-h-12 items-center justify-between gap-3 py-2">
                      <div className="min-w-0"><p className="truncate font-mono text-xs">{o.address}</p><p className="truncate text-xs text-mute">{o.attribute ?? ''} · team {o.team}</p></div>
                      <span className="fig whitespace-nowrap text-xs text-ink2">{o.count} times</span>
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
