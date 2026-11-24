import { DailyChart, Donut, OverruleTrend, StackedHBars } from '../components/Charts';
import FindingsTable from '../components/FindingsTable';
import { ActionButton, Card, Empty, KpiCard } from '../components/ui';
import { dateTime, hours, num, pct } from '../lib/format';
import { countBy, dailyBySeverity, recurringOffenders, weeklyOverrule } from '../lib/logic';
import { actionLinks } from '../lib/url';
import type { PageProps } from './shared';

export default function Overview({ data, filters, eps, kpis, open }: PageProps) {
  const links = actionLinks(data.links, filters.repo);
  const daily = dailyBySeverity(eps, filters, data.asOf);
  const byTeam = [...new Set(eps.map((e) => e.team))].map((team) => {
    const row: Record<string, number | string> = { name: team, critical: 0, high: 0, medium: 0, low: 0 };
    for (const e of eps) if (e.team === team) row[e.severity] = (Number(row[e.severity]) || 0) + 1;
    return row as { name: string; critical: number; high: number; medium: number; low: number };
  }).sort((a, b) => b.critical + b.high + b.medium + b.low - (a.critical + a.high + a.medium + a.low)).slice(0, 8);
  const split = countBy(eps, (e) => e.driftType).map(([name, value]) => ({ name, value }));
  const trend = weeklyOverrule(eps);
  const offenders = recurringOffenders(eps).slice(0, 6);
  const anomalies = data.analytics.dayAnomalies.slice(0, 3);
  const k = kpis;
  const coverageNote = k.managed === null ? 'unknown for this view' : `${num(k.managed)} managed, ${num(k.unmanaged)} outside code`;

  if (!data.episodes.length) {
    return (
      <div className="card"><Empty title="No drift recorded yet" icon="shield">Run DriftPilot at least once. As soon as a scan is saved to the history, this page fills in by itself.</Empty></div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div><h2 className="h-page">Overview</h2><p className="text-sm text-mute">How much drift there is, how fast it gets fixed, and whether people trust DriftPilot&apos;s verdicts.</p></div>
      </div>

      {data.monitor.alerts.length > 0 && (
        <div role="alert" className="rounded-xl border border-crit/40 bg-crit/10 p-3 text-sm">
          <p className="font-semibold text-crit">Verdict monitor</p>
          <ul className="ml-4 list-disc">{data.monitor.alerts.map((a) => <li key={a}>{a}</li>)}</ul>
        </div>
      )}

      <section aria-label="Key numbers" className="grid grid-cols-2 gap-2.5 sm:gap-3 xl:grid-cols-4">
        <KpiCard label="IaC coverage" value={pct(k.iacCoverage)} origin="aws" detail={coverageNote} hint="Share of resources that are managed by code (managed ÷ managed + unmanaged). Higher is better." tone={k.iacCoverage !== null && k.iacCoverage < 80 ? 'bad' : undefined} />
        <KpiCard label="Drift rate" value={pct(k.driftRate)} origin="aws" detail={`${num(k.driftedResources)} distinct resources drifted`} hint="Distinct drifted resources ÷ managed resources. Lower is better." />
        <KpiCard label="Open drift" value={num(k.openCount)} origin="driftpilot" detail={k.oldestOpenHours === null ? 'nothing open' : `oldest open for ${hours(k.oldestOpenHours)}`} hint="Episodes not resolved yet." tone={k.openCount ? 'bad' : 'good'} />
        <KpiCard label="Mean time to resolve" value={hours(k.mttrHours)} origin="driftpilot" hint="Average time from first seen until the first scan that no longer saw the drift." />
        <KpiCard label="Overrule rate" value={pct(k.overruleRate)} origin="driftpilot" detail={`${num(k.decided)} human decisions`} hint="Share of decided findings where a person disagreed with DriftPilot." />
        <KpiCard label="Alert precision" value={pct(k.alertPrecision)} origin="driftpilot" hint="Accepted ÷ (accepted + overruled). Higher means DriftPilot is usually right." />
        <KpiCard label="Recurring offenders" value={num(k.recurringOffenders)} origin="driftpilot" hint="Settings that drifted 3 or more times in this view." />
        <KpiCard label="Episodes in view" value={num(k.episodes)} origin="driftpilot" detail={data.asOf ? `latest scan ${dateTime(data.asOf)}` : undefined} hint="One episode is one stretch of consecutive scans where a setting stayed drifted." />
      </section>

      {eps.length === 0 ? (
        <div className="card"><Empty title="No episodes match these filters">Widen the date range or press Reset in the filter bar.</Empty></div>
      ) : (
        <>
          <div className="grid gap-4 xl:grid-cols-3">
            <Card title="New drift per day" subtitle="Stacked by severity" className="xl:col-span-2"><DailyChart rows={daily} /></Card>
            <Card title="Drift type" subtitle="Infrastructure vs database"><Donut rows={split} label={`Donut chart of episodes by drift type: ${split.map((s) => `${s.name} ${s.value}`).join(', ')}`} /></Card>
          </div>
          <div className="grid gap-4 xl:grid-cols-2">
            <Card title="Episodes by team" subtitle="Top 8, stacked by severity"><StackedHBars rows={byTeam} label="Bar chart of drift episodes per team by severity" /></Card>
            <Card title="Overrule trend" subtitle="Share of decided findings a person overruled, per week">
              {trend.length ? <OverruleTrend rows={trend} threshold={data.monitor.overruleThreshold} /> : <Empty title="No human decisions yet">Accept or overrule a DriftPilot issue or PR and the trend appears here.</Empty>}
            </Card>
          </div>
        </>
      )}

      <div className="grid gap-4 xl:grid-cols-3">
        <Card title="Recurring offenders" subtitle="Same setting, 3+ episodes" className="xl:col-span-1">
          {offenders.length ? (
            <ul className="divide-y divide-line">
              {offenders.map((o) => (
                <li key={`${o.address}${o.attribute}`} className="flex items-center justify-between gap-3 py-2 text-sm">
                  <div className="min-w-0"><p className="truncate font-mono text-xs font-medium">{o.address}</p><p className="truncate text-xs text-mute">{o.attribute ?? ''} · {o.team}</p></div>
                  <span className="chip border-high/40 bg-high/10 text-high">{o.count}×</span>
                </li>
              ))}
            </ul>
          ) : <Empty title="No repeat offenders in this view" />}
          {anomalies.length > 0 && (
            <div className="mt-4 border-t border-line pt-3">
              <p className="h-card mb-1.5">Unusual days</p>
              <ul className="space-y-1 text-xs text-mute">{anomalies.map((a) => <li key={a.day}><span className="font-medium text-ink">{a.day}</span>: {a.newEpisodes} new episodes (usual {a.usual.toFixed(1)})</li>)}</ul>
            </div>
          )}
        </Card>
        <Card title="Take action on GitHub" subtitle="Links only. This page holds no tokens and changes nothing." className="xl:col-span-2">
          {links.scan || links.settings || links.source ? (
            <div className="grid gap-4 sm:grid-cols-3">
              <ActionButton href={links.scan} icon="play" label="Run a scan now" hint="What happens when I click: opens this repo's workflow page on GitHub. GitHub asks you to log in, then you press its own Run workflow button. DriftPilot only scans and reports." primary />
              <ActionButton href={links.settings} icon="edit" label="Edit settings" hint="What happens when I click: opens .driftpilot.yml in GitHub's editor. GitHub asks you to log in. Saving makes a normal commit that your team can review." />
              <ActionButton href={links.source} icon="github" label="Dashboard source repo" hint="What happens when I click: opens the repository on GitHub, where the code, issues and pull requests live." />
            </div>
          ) : <p className="text-sm text-mute">No GitHub repo is known for this data, so the action buttons are hidden. Set <code className="font-mono">dashboard.links.repo</code> in <code className="font-mono">.driftpilot.yml</code>.</p>}
          <p className="mt-4 text-sm font-semibold">Latest findings</p>
          <div className="mt-2"><FindingsTable rows={eps} onOpen={open} compact /></div>
        </Card>
      </div>
    </div>
  );
}
