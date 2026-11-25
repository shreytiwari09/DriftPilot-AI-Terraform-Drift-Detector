import { CallsChart } from '../components/Charts';
import FindingsTable from '../components/FindingsTable';
import { Card, Empty, Icon, StatCard } from '../components/ui';
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
    <div className="stagger space-y-6">
      <section aria-label="Guardrail numbers" className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Never-soften overrides" value={num(s.neverSoften.length)} detail="kept serious" hint="Security weakenings (open admin ports, public storage...) the AI tried to call harmless. DriftPilot kept them serious." />
        <StatCard label="Suspicious inputs" value={num(s.suspicious.length)} detail="sent to a person" hint="Findings whose text looked like instructions to the AI. They always go to a person." />
        <StatCard label="LLM calls" value={g?.hasAudit ? num(s.calls) : '—'} detail={g?.hasAudit ? `${s.runsWithCalls} runs with calls` : 'no audit log in this data'} hint="Every AI call is counted in an audit log (hashes only, never the text)." />
        <StatCard label="Call budget" value={budget ? `${s.peakCalls} / ${budget}` : '—'} bad={over} detail={peakShare} hint="A hard cap per run. When it is reached DriftPilot stops asking the AI and marks findings for a person." />
      </section>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
        <Card title="LLM calls per run" subtitle={budget ? `Dashed line is the budget of ${budget} calls per run` : 'No budget recorded'}>
          {chartRows.length ? <CallsChart rows={chartRows} limit={budget} /> : <Empty title={g?.hasAudit ? 'No LLM calls in this view' : 'No audit log found'} icon="shield">{g?.hasAudit ? 'Widen the date range.' : 'The audit log (history/audit.jsonl) is written by every scan that uses the AI. Without it, only the guardrail marks on findings can be shown.'}</Empty>}
          {s.invalid > 0 && <p className="mt-3 text-xs text-mute">{s.invalid} answers could not be parsed; those findings fell back to &quot;investigate&quot; (a person looks).</p>}
        </Card>
        <Card title="How the guardrails work" subtitle="The checks that matter run as plain code, not as AI">
          <ul className="space-y-4 text-sm text-ink2">
            <li className="flex gap-3"><Icon name="shield" className="mt-0.5 h-4 w-4" /><span><span className="font-medium text-ink">Never-soften list.</span> For listed security weakenings the AI can make a verdict stricter, never softer.</span></li>
            <li className="flex gap-3"><Icon name="alert" className="mt-0.5 h-4 w-4" /><span><span className="font-medium text-ink">Suspicious input.</span> Text that tries to instruct the AI (&quot;ignore previous instructions&quot;) can never make a finding &quot;not real&quot;.</span></li>
            <li className="flex gap-3"><Icon name="check" className="mt-0.5 h-4 w-4" /><span><span className="font-medium text-ink">Limits.</span> Caps on AI calls, prompt size, PRs, files per PR and patch size.</span></li>
            <li className="flex gap-3"><Icon name="findings" className="mt-0.5 h-4 w-4" /><span><span className="font-medium text-ink">Audit log.</span> One line per AI call, with hashes instead of text.</span></li>
          </ul>
        </Card>
      </div>

      <Card flush title="Findings a guardrail touched" subtitle="Select a row to see why">
        {touched.length ? (
          <>
            <p className="fig mb-4 px-4 text-xs text-mute sm:px-5">{s.neverSoften.length} never-soften · {s.suspicious.length} suspicious input</p>
            <div className="border-t border-line"><FindingsTable rows={touched} onOpen={open} /></div>
          </>
        ) : <Empty title="No guardrail fired in this view" icon="check">That is normal on quiet days. When one fires, the finding shows up here with the reason.</Empty>}
      </Card>
    </div>
  );
}
