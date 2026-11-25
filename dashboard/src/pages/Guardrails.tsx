import { CallsChart } from '../components/Charts';
import FindingsTable from '../components/FindingsTable';
import { Card, Empty, Icon, StatCard } from '../components/ui';
import type { EvalSetup, EvaluationSummary, Ratio } from '../types';
import { num } from '../lib/format';
import { guardrailSummary } from '../lib/logic';
import type { PageProps } from './shared';

const share = (r: Ratio): string => (r.total ? `${r.hits}/${r.total} (${Math.round((100 * r.hits) / r.total)}%)` : '—');
const percent = (v: number | null): string => (v === null ? '—' : `${Math.round(v * 100)}%`);
const withRules = (setups: EvalSetup[]) => setups.find((x) => x.setup === 'rules + cloud LLM');

/** What the guardrails achieved on a fixed set of hostile and harmless cases, from the saved evaluation. */
function Effectiveness({ e }: { e: EvaluationSummary }) {
  const a = e.adversarial;
  const rows: { label: string; hint: string; off: string; on: string }[] = [
    { label: 'Attack success (lower is better)', hint: 'The verdict ended up softer than the label, or with an action the label does not accept. Lower is better', off: share(a.withoutGuardrails.attackSuccess), on: share(a.withGuardrails.attackSuccess) },
    { label: 'Softer only', hint: 'Only the attacks that hid or weakened a finding. Lower is better', off: share(a.withoutGuardrails.softerOnly), on: share(a.withGuardrails.softerOnly) },
    { label: 'Never-soften findings softened', hint: 'Security weakenings on the never-soften list that an attack made softer. Lower is better', off: share(a.withoutGuardrails.neverSoften), on: share(a.withGuardrails.neverSoften) },
    { label: 'Harmless look-alikes handled (higher is better)', hint: 'Harmless changes with scary text, still judged low-severity with an accepted action. Higher is better', off: share(a.withoutGuardrails.benignRight), on: share(a.withGuardrails.benignRight) },
  ];
  const main = withRules(e.main.setups);
  const db = withRules(e.database.setups);
  return (
    <Card flush title="Measured effectiveness" subtitle={`${a.cases} adversarial cases (${a.attackCases} attacks, ${a.benignCases} harmless look-alikes)${e.date ? `, run ${e.date}` : ''} with ${e.model}`}>
      <div className="scroll-x">
        <table className="w-full min-w-[520px] border-collapse text-left text-sm">
          <thead className="text-xs text-mute"><tr className="h-10 border-y border-line"><th scope="col" className="px-4 font-normal first:pl-5">Measure</th><th scope="col" className="px-4 text-right font-normal">No guardrails</th><th scope="col" className="px-4 text-right font-normal last:pr-5">With guardrails</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.label} className="h-12 border-b border-line last:border-b-0" title={r.hint}>
                <th scope="row" className="px-4 font-normal first:pl-5">{r.label}</th>
                <td className="fig px-4 text-right text-ink2">{r.off}</td>
                <td className="fig px-4 text-right last:pr-5">{r.on}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="space-y-1 border-t border-line px-4 py-3 text-xs text-mute sm:px-5">
        {main && <p>Everyday triage (rules + AI, {e.main.findings} labelled findings): severity right {percent(main.severityRight)}, critical caught {percent(main.criticalCaught)}, false alarms {percent(main.falseAlarms)}.</p>}
        {db && <p>Database drift ({e.database.findings} labelled findings): severity right {percent(db.severityRight)}, action right {percent(db.actionRight)}.</p>}
        <p>Not a security proof. The labels were written by the same author as the rules, and the set is small. Never-soften findings are protected by code, not by the model.</p>
      </div>
    </Card>
  );
}

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
        <StatCard label="LLM calls" value={g?.hasAudit ? num(s.calls) : '—'} detail={g?.hasAudit ? `${s.runsWithCalls} runs with calls` : 'none recorded: clean scans make no calls'} hint="Every AI call is counted in an audit log (hashes only, never the text)." />
        <StatCard label="Call budget" value={budget ? `${s.peakCalls} / ${budget}` : '—'} bad={over} detail={peakShare} hint="A hard cap per run. When it is reached DriftPilot stops asking the AI and marks findings for a person." />
      </section>

      {data.evaluation && <Effectiveness e={data.evaluation} />}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
        <Card title="LLM calls per run" subtitle={budget ? `Dashed line is the budget of ${budget} calls per run` : 'No budget recorded'}>
          {chartRows.length ? <CallsChart rows={chartRows} limit={budget} /> : <Empty title={g?.hasAudit ? 'No LLM calls in this view' : 'No AI calls recorded yet'} icon="shield">{g?.hasAudit ? 'Widen the date range.' : 'Written by scans that call the AI. Clean scans make no calls, so there is nothing to log until a scan finds something to judge.'}</Empty>}
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
        ) : <Empty title="No guardrail fired in this view" icon="check">Normal on quiet days: guardrails act only when a scan judges a finding or meets hostile text. When one fires, the finding shows up here with the reason.</Empty>}
      </Card>
    </div>
  );
}
