import { CallsChart } from '../components/Charts';
import FindingsTable from '../components/FindingsTable';
import { Card, Empty, Icon, KpiCard, Tag } from '../components/ui';
import { num } from '../lib/format';
import { guardrailSummary } from '../lib/logic';
import type { PageProps } from './shared';

export default function Guardrails({ data, filters, eps, open }: PageProps) {
  const g = data.guardrails;
  const s = guardrailSummary(eps, g?.runs ?? [], filters, g?.llmCallLimit ?? null);
  const touched = eps.filter((e) => e.guardrails?.length);
  const budget = s.limit;
  const peakShare = budget && s.peakCalls ? `${s.peakCalls} of ${budget} in the busiest run` : s.peakCalls ? `${s.peakCalls} in the busiest run` : 'no calls recorded';
  const chartRows = s.runs.filter((r) => r.calls > 0).slice(-60).map((r) => ({ name: r.t, calls: r.calls, invalid: r.invalid }));
  const over = budget !== null && s.peakCalls > budget;

  return (
    <div className="space-y-5">
      <div><h2 className="h-page">Guardrails</h2><p className="text-sm text-mute">What stops the AI from being talked into something unsafe, and how much it is allowed to spend. The checks that matter run as plain code, not as AI.</p></div>

      <section aria-label="Guardrail numbers" className="grid grid-cols-2 gap-2.5 sm:gap-3 xl:grid-cols-4">
        <KpiCard label="Never-soften overrides" value={num(s.neverSoften.length)} origin="driftpilot" hint="Security weakenings (open admin ports, public storage...) the AI tried to call harmless. DriftPilot kept them serious." />
        <KpiCard label="Suspicious inputs" value={num(s.suspicious.length)} origin="driftpilot" hint="Findings whose text looked like instructions to the AI. They always go to a person." />
        <KpiCard label="LLM calls" value={g?.hasAudit ? num(s.calls) : '—'} origin="driftpilot" detail={g?.hasAudit ? `${s.runsWithCalls} runs with calls` : 'no audit log in this data'} hint="Every AI call is counted in an audit log (hashes only, never the text)." />
        <KpiCard label="Call budget" value={budget ? `${s.peakCalls} / ${budget}` : '—'} origin="driftpilot" detail={peakShare} hint="A hard cap per run. When it is reached DriftPilot stops asking the AI and marks findings for a person." tone={over ? 'bad' : undefined} />
      </section>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card title="LLM calls per run" subtitle={budget ? `Dashed line = budget of ${budget} calls per run` : 'No budget recorded'} className="xl:col-span-2">
          {chartRows.length ? <CallsChart rows={chartRows} limit={budget} /> : <Empty title={g?.hasAudit ? 'No LLM calls in this view' : 'No audit log found'} icon="shield">{g?.hasAudit ? 'Widen the date range.' : 'The audit log (history/audit.jsonl) is written by every scan that uses the AI. Without it, only the guardrail marks on findings can be shown.'}</Empty>}
          {s.invalid > 0 && <p className="mt-2 text-xs text-mute">{s.invalid} answers could not be parsed; those findings fell back to &quot;investigate&quot; (a person looks).</p>}
        </Card>
        <Card title="How the guardrails work">
          <ul className="space-y-3 text-sm">
            <li className="flex gap-2"><Icon name="shield" className="mt-0.5 h-4 w-4 shrink-0 text-brand" /><span><b>Never-soften list.</b> For listed security weakenings the AI can make a verdict stricter, never softer.</span></li>
            <li className="flex gap-2"><Icon name="alert" className="mt-0.5 h-4 w-4 shrink-0 text-high" /><span><b>Suspicious input.</b> Text that tries to instruct the AI (&quot;ignore previous instructions&quot;) can never make a finding &quot;not real&quot;.</span></li>
            <li className="flex gap-2"><Icon name="check" className="mt-0.5 h-4 w-4 shrink-0 text-ok" /><span><b>Limits.</b> Caps on AI calls, prompt size, PRs, files per PR and patch size.</span></li>
            <li className="flex gap-2"><Icon name="findings" className="mt-0.5 h-4 w-4 shrink-0 text-teal" /><span><b>Audit log.</b> One line per AI call, with hashes instead of text.</span></li>
          </ul>
        </Card>
      </div>

      <Card title="Findings a guardrail touched" subtitle="Click a row to see why">
        {touched.length ? (
          <>
            <div className="mb-2 flex gap-1.5"><Tag tone="warn">{s.neverSoften.length} never-soften</Tag><Tag tone="warn">{s.suspicious.length} suspicious input</Tag></div>
            <FindingsTable rows={touched} onOpen={open} />
          </>
        ) : <Empty title="No guardrail fired in this view" icon="check">That is normal on quiet days. When one fires, the finding shows up here with the reason.</Empty>}
      </Card>
    </div>
  );
}
