import { DailyChart, OverruleTrend, SeverityLegend, severityTotals } from '../components/Charts';
import FindingsTable from '../components/FindingsTable';
import NeedsAttention from '../components/NeedsAttention';
import { ActionButton, Card, Empty, MiniStat, RankedBars, StatCard } from '../components/ui';
import { dateTime, hours, num, pct } from '../lib/format';
import { countBy, dailyBySeverity, recurringOffenders, weeklyOverrule } from '../lib/logic';
import { buildHash } from '../lib/route';
import { trendDeltas } from '../lib/trend';
import { useNow } from '../lib/useNow';
import { actionLinks } from '../lib/url';
import { useMemo } from 'react';
import { SEVERITIES } from '../types';
import type { PageProps } from './shared';

export default function Overview({ data, filters, eps, kpis, open }: PageProps) {
  const now = useNow();
  const links = actionLinks(data.links, filters.repo);
  const deltas = useMemo(() => trendDeltas(data.episodes, data.runs, filters, data.asOf, kpis), [data, filters, kpis]);
  const attention = (
    <NeedsAttention data={data} eps={eps} now={now} onOpen={open} seeAllHref={buildHash({ page: 'findings', filters: { ...filters, status: 'open' }, open: '' })} />
  );
  const daily = dailyBySeverity(eps, filters, data.asOf);
  const byTeam = [...new Set(eps.map((e) => e.team))].map((team) => {
    const segments: Record<string, number> = {};
    let value = 0;
    for (const e of eps) if (e.team === team) { segments[e.severity] = (segments[e.severity] ?? 0) + 1; value += 1; }
    return { name: team, value, segments };
  }).sort((a, b) => b.value - a.value).slice(0, 8);
  const split = countBy(eps, (e) => e.driftType).map(([name, value]) => ({ name, value }));
  const sev = SEVERITIES.map((s) => ({ name: s.charAt(0).toUpperCase() + s.slice(1), value: eps.filter((e) => e.severity === s).length, segments: { [s]: eps.filter((e) => e.severity === s).length } }));
  const trend = weeklyOverrule(eps);
  const offenders = recurringOffenders(eps).slice(0, 6);
  const anomalies = data.analytics.dayAnomalies.slice(0, 3);
  const k = kpis;
  const coverageNote = k.managed === null ? 'unknown for this view' : `${num(k.managed)} managed, ${num(k.unmanaged)} outside code`;
  const recent = data.monitor.recentOverruleRate;
  const baseline = data.monitor.baselineOverruleRate;
  const rateOf = (r: number) => `${Math.round(r * 100)}%`;
  const overruleNote = recent !== null && baseline !== null ? `${rateOf(recent)} in last 14 days vs ${rateOf(baseline)} before` : `${num(k.decided)} human decisions`;

  if (!data.episodes.length) {
    return (
      <div className="stagger space-y-6">
        {attention}
        <div className="card"><Empty title="No drift recorded yet" icon="shield">Run DriftPilot at least once. As soon as a scan is saved to the history, this page fills in by itself.</Empty></div>
      </div>
    );
  }

  return (
    <div className="stagger space-y-6">
      {attention}
      {data.monitor.alerts.length > 0 && (
        <div role="alert" className="rounded-xl border border-line bg-surface p-4 text-sm">
          <p className="flex items-center gap-2 font-medium"><span className="h-1.5 w-1.5 rounded-full bg-crit" aria-hidden="true" />Verdict monitor</p>
          <ul className="mt-2 list-disc space-y-1 pl-6 text-ink2">{data.monitor.alerts.map((a) => <li key={a}>{a}</li>)}</ul>
        </div>
      )}

      <section aria-label="Key numbers" className="space-y-4">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatCard label="IaC coverage" value={pct(k.iacCoverage)} aws detail={coverageNote} hint="Share of resources managed by code: managed ÷ (managed + unmanaged). Higher is better." />
          <StatCard label="Drift rate" value={pct(k.driftRate)} aws delta={deltas?.driftRate} detail={`${num(k.driftedResources)} distinct resources drifted`} hint="Distinct drifted resources ÷ managed resources. Lower is better." />
          <StatCard label="Open drift" value={num(k.openCount)} accent delta={deltas?.open} detail={k.oldestOpenHours === null ? 'nothing open' : `oldest open for ${hours(k.oldestOpenHours)}`} hint="Episodes not resolved yet." />
          <StatCard label="Mean time to resolve" value={hours(k.mttrHours)} delta={deltas?.mttr} detail="first seen to first clean scan" hint="Average time from first seen until the first scan that no longer saw the drift." />
        </div>
        <div>
          <h2 className="mb-2 text-[13px] text-ink2">Trust in DriftPilot</h2>
          <div className="card grid grid-cols-2 divide-line lg:grid-cols-4 lg:divide-x">
            <MiniStat label="Overrule rate" value={pct(k.overruleRate)} detail={overruleNote} hint="Share of decided findings where a person disagreed with DriftPilot." />
            <MiniStat label="Alert precision" value={pct(k.alertPrecision)} detail="accepted ÷ decided" hint="Accepted ÷ (accepted + overruled). Higher means DriftPilot is usually right." />
            <MiniStat label="Recurring offenders" value={num(k.recurringOffenders)} detail="settings with 3+ episodes" hint="Settings that drifted 3 or more times in this view." />
            <MiniStat label="Episodes in view" value={num(k.episodes)} detail={data.asOf ? `latest scan ${dateTime(data.asOf)}` : undefined} hint="One episode is one stretch of consecutive scans where a setting stayed drifted." />
          </div>
        </div>
        <p className="text-xs text-mute"><span className="font-mono">†</span> AWS Well-Architected metrics. The other figures are DriftPilot&apos;s own</p>
      </section>

      {eps.length === 0 ? (
        <div className="card"><Empty title="No episodes match these filters">Widen the date range or press Reset in the filter bar.</Empty></div>
      ) : (
        <>
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
            <Card title="New drift per day" subtitle="Stacked by severity" action={<SeverityLegend totals={severityTotals(daily)} />}><DailyChart rows={daily} /></Card>
            <Card title="Drift type" subtitle="Infrastructure vs database">
              <RankedBars rows={split} label={`Episodes by drift type: ${split.map((s) => `${s.name} ${s.value}`).join(', ')}`} />
              <h3 className="mb-2 mt-6 text-[13px] text-ink2">Severity</h3>
              <RankedBars rows={sev} label="Episodes by severity" />
            </Card>
          </div>
          <div className="grid gap-6 xl:grid-cols-2">
            <Card title="Episodes by team" subtitle="Top 8, by severity"><RankedBars rows={byTeam} label="Drift episodes per team by severity" /></Card>
            <Card title="Overrule trend" subtitle="Share of decided findings a person overruled, per week">
              {trend.length ? <OverruleTrend rows={trend} threshold={data.monitor.overruleThreshold} /> : <Empty title="No human decisions yet">Accept or overrule a DriftPilot issue or PR and the trend appears here.</Empty>}
            </Card>
          </div>
        </>
      )}

      <div className="grid gap-6 xl:grid-cols-3">
        <Card title="Recurring offenders" subtitle="Same setting, 3+ episodes" className="xl:col-span-1">
          {offenders.length ? (
            <ul className="divide-y divide-line">
              {offenders.map((o) => (
                <li key={`${o.address}${o.attribute}`} className="flex min-h-12 items-center justify-between gap-3 py-2 text-sm">
                  <div className="min-w-0"><p className="truncate font-mono text-xs">{o.address}</p><p className="truncate text-xs text-mute">{o.attribute ?? ''} · {o.team}</p></div>
                  <span className="fig whitespace-nowrap text-xs text-ink2">{o.count}×</span>
                </li>
              ))}
            </ul>
          ) : <Empty title="No repeat offenders in this view" />}
          {anomalies.length > 0 && (
            <div className="mt-6 border-t border-line pt-4">
              <h3 className="h-card mb-2">Unusual days</h3>
              <ul className="space-y-1 text-xs text-ink2">{anomalies.map((a) => <li key={a.day}><span className="fig text-ink">{a.day}</span> {a.newEpisodes} new episodes (usual {a.usual.toFixed(1)})</li>)}</ul>
            </div>
          )}
        </Card>
        <Card title="Take action on GitHub" subtitle="Links only. This page holds no tokens and changes nothing" className="xl:col-span-2">
          {links.scan || links.settings || links.source ? (
            <div className="grid gap-4 sm:grid-cols-3">
              <ActionButton href={links.scan} icon="play" label="Run a scan now" hint="What happens when I click: opens this repo's workflow page on GitHub. GitHub asks you to log in, then you press its own Run workflow button. DriftPilot only scans and reports." />
              <ActionButton href={links.settings} icon="edit" label="Edit settings" hint="What happens when I click: opens .driftpilot.yml in GitHub's editor. GitHub asks you to log in. Saving makes a normal commit that your team can review." />
              <ActionButton href={links.source} icon="github" label="Dashboard source repo" hint="What happens when I click: opens the repository on GitHub, where the code, issues and pull requests live." />
            </div>
          ) : <p className="text-sm text-ink2">No GitHub repo is known for this data, so the action buttons are hidden. Set <code className="font-mono">dashboard.links.repo</code> in <code className="font-mono">.driftpilot.yml</code>.</p>}
          <h3 className="h-card mb-2 mt-6">Latest findings</h3>
          <div className="-mx-4 sm:-mx-5"><FindingsTable rows={eps} onOpen={open} compact /></div>
        </Card>
      </div>
    </div>
  );
}
