import { Card, OriginLabel, type MetricOrigin } from '../components/ui';
import { dateTime } from '../lib/format';
import type { PageProps } from './shared';

const METRICS: { name: string; origin: MetricOrigin; formula: string; text: string }[] = [
  { name: 'IaC coverage', origin: 'aws', formula: 'managed ÷ (managed + unmanaged)', text: 'How much of what exists is described in code. 100% means nothing was created by hand.' },
  { name: 'Drift rate', origin: 'aws', formula: 'distinct drifted resources ÷ managed resources', text: 'How much of the managed estate has drifted in the chosen period.' },
  { name: 'Open drift', origin: 'driftpilot', formula: 'episodes not yet resolved', text: 'Drift that is still there at the latest scan. "Oldest open" is how long the first one has been waiting.' },
  { name: 'Mean time to resolve', origin: 'driftpilot', formula: 'first seen → first scan without it', text: 'How quickly drift disappears once DriftPilot has found it.' },
  { name: 'Overrule rate', origin: 'driftpilot', formula: 'overruled ÷ (accepted + overruled)', text: 'How often a person disagreed with DriftPilot by closing its issue or PR as unwanted. A rising rate means verdicts may be going stale.' },
  { name: 'Alert precision', origin: 'driftpilot', formula: 'accepted ÷ (accepted + overruled)', text: 'How often DriftPilot was right in the eyes of the people who decided.' },
  { name: 'Recurring offenders', origin: 'driftpilot', formula: 'settings with 3 or more episodes', text: 'Things that keep getting changed by hand. Usually a sign that the code or a process needs fixing.' },
];

const GLOSSARY: [string, string][] = [
  ['Drift', 'The real thing no longer matches the code (Terraform) or the migration files (database).'],
  ['Episode', 'One stretch of consecutive scans where the same setting stayed drifted. If it is fixed and drifts again, that is a new episode.'],
  ['Decided by', 'Who judged the finding: a rule from the rule pack, the AI model (llm), or a policy/guardrail override.'],
  ['Human outcome', 'accepted = a person acted on it, overruled = a person said it was wrong, pending = nobody reacted yet.'],
  ['Unmanaged', 'Resources that exist in the cloud account or repo but are not in Terraform at all.'],
];

export default function About({ data }: PageProps) {
  return (
    <div className="stagger space-y-6">
      <Card flush title="Metrics" subtitle="Plain-language meaning of every figure. Two come from the AWS Well-Architected guidance, the rest are DriftPilot's own">
        <div className="scroll-x">
          <table className="w-full min-w-[640px] border-collapse text-left text-sm">
            <thead className="text-xs text-mute"><tr className="h-10 border-y border-line"><th scope="col" className="px-4 font-normal first:pl-5 last:pr-5">Metric</th><th scope="col" className="px-4 font-normal first:pl-5 last:pr-5">Origin</th><th scope="col" className="px-4 font-normal first:pl-5 last:pr-5">Formula</th><th scope="col" className="px-4 font-normal first:pl-5 last:pr-5">What it tells you</th></tr></thead>
            <tbody>
              {METRICS.map((m) => (
                <tr key={m.name} className="border-b border-line align-top last:border-b-0">
                  <th scope="row" className="whitespace-nowrap px-4 py-3 font-medium first:pl-5">{m.name}</th>
                  <td className="whitespace-nowrap px-4 py-3"><OriginLabel origin={m.origin} /></td>
                  <td className="px-4 py-3 font-mono text-xs text-ink2">{m.formula}</td>
                  <td className="px-4 py-3 text-ink2 last:pr-5">{m.text}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Words used on this page"><dl className="space-y-4 text-sm">{GLOSSARY.map(([t, d]) => <div key={t}><dt className="font-medium">{t}</dt><dd className="text-ink2">{d}</dd></div>)}</dl></Card>
        <Card title="Safe by design">
          <ul className="list-disc space-y-2 pl-5 text-sm text-ink2">
            <li>This page is read-only. It holds <span className="font-medium text-ink">no tokens and no secrets</span>.</li>
            <li>Buttons are plain links to github.com. GitHub asks you to log in and approve; DriftPilot itself never changes anything.</li>
            <li>The &quot;suggested command&quot; is text to copy. It is never run by this page.</li>
            <li>Account IDs and ARNs are masked before they reach <code className="font-mono">data.json</code>.</li>
            <li>Filters live in the address bar: copy the link to share exactly this view.</li>
          </ul>
        </Card>
      </div>
      <Card title="This data">
        <dl className="grid gap-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
          <div><dt className="label">Generated</dt><dd className="fig">{dateTime(data.generated)}</dd></div>
          <div><dt className="label">Latest scan</dt><dd className="fig">{dateTime(data.asOf)}</dd></div>
          <div><dt className="label">Episodes / runs</dt><dd className="fig">{data.episodes.length.toLocaleString('en-US')} / {data.runs.length.toLocaleString('en-US')}</dd></div>
          <div><dt className="label">Resource names</dt><dd>{data.publishAddresses ? 'shown' : 'hidden (hashes)'}</dd></div>
        </dl>
      </Card>
    </div>
  );
}
