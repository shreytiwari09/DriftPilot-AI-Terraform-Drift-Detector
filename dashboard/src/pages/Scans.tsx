import { useState } from 'react';
import PauseControl from '../components/PauseControl';
import { Card, Empty, ExternalLink, StatCard, StatusText } from '../components/ui';
import { controlTarget, type ControlTarget, type WorkflowState } from '../lib/githubControl';
import { ago, dateTime, hours, num } from '../lib/format';
import { cadenceOf, isSimulated, recentRuns, referenceNow, STATUS_LABEL, summarizeScans, type ScanStatus } from '../lib/scans';
import { actionLinks } from '../lib/url';
import { useNow } from '../lib/useNow';
import type { PageProps } from './shared';

const STATUS_DOT: Record<ScanStatus, string> = { on_time: 'bg-ok', late: 'bg-med', stale: 'bg-crit' };
const TH = 'whitespace-nowrap px-3 font-normal first:pl-5 last:pr-5';
const TD = 'px-3 first:pl-5 last:pr-5';

/** How long until a change shows up, step by step. Honest: the data changes only when a scan runs. */
function Freshness({ cadence }: { cadence: number }) {
  const rows: [string, string][] = [
    ['A cloud change event (event-triggered run)', 'About 15 s for the event to reach the workflow, then 1 to 2 min for the scan'],
    ['The schedule', `Every ${cadence} h, then 1 to 2 min for the scan. A change waits up to ${cadence} h`],
    ['Publishing', 'About 1 min for GitHub Pages to deploy the new data.json'],
    ['This page', 'Re-reads data.json every 5 min. The refresh button in the header does it now'],
  ];
  return (
    <Card flush title="How fresh is this data" subtitle="Near real time, not streaming. The data changes only when a scan runs">
      <div className="scroll-x">
        <table className="w-full min-w-[480px] border-collapse text-left text-sm">
          <thead className="text-xs text-mute"><tr className="h-10 border-y border-line"><th scope="col" className={TH}>Trigger</th><th scope="col" className={TH}>Delay</th></tr></thead>
          <tbody>
            {rows.map(([name, delay]) => (
              <tr key={name} className="border-b border-line align-top last:border-b-0">
                <th scope="row" className={`${TD} py-3 font-medium`}>{name}</th>
                <td className={`${TD} py-3 text-ink2`}>{delay}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="border-t border-line px-4 py-3 text-xs text-mute sm:px-5">After an event-triggered scan, expect the change here in about 2 to 9 min. After a scheduled one, the wait for the next run comes first.</p>
    </Card>
  );
}

function Schedule({ cadence, manage, lampAmberHours, target, onWorkflow }: { cadence: number; manage: string | null; lampAmberHours: number; target: ControlTarget | null; onWorkflow: (w: WorkflowState | null) => void }) {
  return (
    <Card title="Schedule" subtitle="Scans run from your GitHub workflow. By default this page only reads them" action={manage ? <ExternalLink href={manage} className="btn btn-sm" hint="Manage schedule: opens this repo's workflow page on GitHub. GitHub asks you to log in. DriftPilot itself changes nothing.">Manage schedule</ExternalLink> : undefined}>
      <p className="fig text-xl font-medium leading-7">Every {cadence} h</p>
      <p className="mb-4 text-xs text-mute">Set by <span className="font-mono">dashboard.scan_every_hours</span> in .driftpilot.yml. It must match the workflow&apos;s cron line</p>
      <ol className="space-y-2 text-sm text-ink2">
        <li><span className="font-medium text-ink">Pause:</span> open the workflow, menu (three dots) &gt; Disable workflow</li>
        <li><span className="font-medium text-ink">Resume:</span> Enable workflow</li>
        <li><span className="font-medium text-ink">Scan now:</span> Run workflow</li>
      </ol>
      <p className="mt-4 text-xs text-mute">While paused, this page keeps showing the last scan, and the lamp turns amber once it is older than {lampAmberHours} h</p>
      {!manage && <p className="mt-2 text-xs text-mute">No GitHub repo is known for this data, so the button is hidden. Set <span className="font-mono">dashboard.links.repo</span></p>}
      {target && <PauseControl target={target} cadence={cadence} onWorkflow={onWorkflow} />}
    </Card>
  );
}

export default function Scans({ data, filters }: PageProps) {
  const now = useNow();
  const cadence = cadenceOf(data);
  const s = summarizeScans(data, now, filters);
  const ref = referenceNow(data, now);
  const runs = recentRuns(s.rows, 20);
  const manage = actionLinks(data.links, filters.repo).scan;
  const simulated = isSimulated(data.note);
  const target = controlTarget(data.links);
  const [workflow, setWorkflow] = useState<WorkflowState | null>(null); // only known while a token is connected

  if (!data.scans || data.scans.streams.length === 0) {
    return (
      <div className="stagger space-y-6">
        <div className="card"><Empty title="No scan health in this data yet" icon="alert">{data.scans ? 'No scans are recorded.' : 'This data.json was made before scan health existed.'} It appears after the next scan saves history.</Empty></div>
        <Freshness cadence={cadence} />
      </div>
    );
  }

  return (
    <div className="stagger space-y-6">
      {workflow === 'disabled' && (
        <div role="status" className="card flex items-start gap-3 px-4 py-3 sm:px-5">
          <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-med" aria-hidden="true" />
          <div className="text-sm"><p className="font-medium">Scans are paused</p><p className="text-ink2">The data below stops changing until you resume them in the Schedule card. Shown only while a token is connected on this page.</p></div>
        </div>
      )}
      <section aria-label="Scan health numbers" className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Streams on time" value={`${s.onTime} / ${s.total}`} detail={`expected every ${cadence} h`} hint="A stream is a repo, environment and drift type. On time means its last scan is at most 1.5 times the expected interval old." />
        <StatCard label="Runs in 24 h" value={num(s.runs24h)} detail="before the latest scan" hint="Scans recorded in the 24 hours before the latest scan, all streams." />
        <StatCard label="Errors in 7 d" value={num(s.errors7d)} detail={s.errors7d ? 'see Recent runs' : 'none reported'} hint="Problems scans reported (a scanner, an event file, opening issues, saving history). The scan still finished and reported its drift." />
        <StatCard label="Longest gap" value={hours(s.longestGapHours)} detail="between runs, last 7 d" hint="The longest wait between two scans of one stream in the 7 days before the latest scan." />
      </section>

      <Card flush title="Scan streams" subtitle={simulated ? 'Simulated data: judged against its own latest scan' : 'Judged against your clock: on time up to 1.5x the interval, late up to 3x, stale beyond'}>
        <div className="scroll-x">
          <table className="w-full min-w-[820px] border-collapse text-left text-sm">
            <thead className="text-xs text-mute">
              <tr className="h-10 border-y border-line">
                <th scope="col" className={TH}>Repo</th><th scope="col" className={TH}>Type</th><th scope="col" className={TH}>Last scan</th><th scope="col" className={TH}>Expected</th><th scope="col" className={TH}>Status</th>
                <th scope="col" className={`${TH} text-right`}>Runs 24 h</th><th scope="col" className={`${TH} text-right`}>Runs 7 d</th><th scope="col" className={`${TH} text-right`}>Errors</th>
              </tr>
            </thead>
            <tbody>
              {s.rows.map((r) => (
                <tr key={`${r.repo}|${r.environment}|${r.driftType}|${r.dir}`} className="h-12 border-b border-line last:border-b-0">
                  <th scope="row" className={`${TD} font-medium`}><span className="block max-w-[240px] truncate" title={r.repo}>{r.repo}</span><span className="block text-xs font-normal text-mute">{r.environment}</span></th>
                  <td className={`${TD} text-ink2`}>{r.driftType}</td>
                  <td className={TD}><span className="block">{ago(new Date(r.lastRun), ref)}</span><span className="fig block text-xs text-mute">{dateTime(r.lastRun)}</span></td>
                  <td className={`${TD} fig whitespace-nowrap text-ink2`}>every {cadence} h</td>
                  <td className={TD}><StatusText dot={STATUS_DOT[r.status]}>{STATUS_LABEL[r.status]}</StatusText></td>
                  <td className={`${TD} fig text-right`}>{r.runCount24h}</td>
                  <td className={`${TD} fig text-right`}>{r.runCount7d}</td>
                  <td className={`${TD} fig text-right ${r.errors7d ? 'text-crit' : 'text-mute'}`}>{r.errors7d}</td>
                </tr>
              ))}
              {s.rows.length === 0 && <tr><td colSpan={8} className="px-5 py-6 text-center text-ink2">No streams match the repo, environment or type filter</td></tr>}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="grid gap-6 xl:grid-cols-2">
        <Schedule cadence={cadence} manage={manage} lampAmberHours={3 * cadence} target={target} onWorkflow={setWorkflow} />
        <Freshness cadence={cadence} />
      </div>

      <Card flush title="Recent runs" subtitle="Newest first, up to 20 across the streams above">
        <div className="scroll-x">
          <table className="w-full min-w-[640px] border-collapse text-left text-sm">
            <caption className="sr-only">Recent scan runs</caption>
            <thead className="text-xs text-mute">
              <tr className="h-10 border-y border-line">
                <th scope="col" className={TH}>Time</th><th scope="col" className={TH}>Stream</th>
                <th scope="col" className={`${TH} text-right`}>Findings</th><th scope="col" className={`${TH} text-right`}>Critical</th><th scope="col" className={`${TH} text-right`}>Noise</th><th scope="col" className={`${TH} text-right`}>Errors</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r, i) => (
                <tr key={`${r.t}|${r.stream}|${i}`} className="h-12 border-b border-line last:border-b-0">
                  <td className={`${TD} fig whitespace-nowrap text-xs text-ink2`}>{dateTime(r.t)}</td>
                  <td className={`${TD} max-w-[320px] truncate`} title={r.stream}>{r.stream}</td>
                  <td className={`${TD} fig text-right`}>{r.findings}</td>
                  <td className={`${TD} fig text-right ${r.critical ? '' : 'text-mute'}`}>{r.critical}</td>
                  <td className={`${TD} fig text-right text-mute`}>{r.noise}</td>
                  <td className={`${TD} fig text-right ${r.errors ? 'text-crit' : 'text-mute'}`}>{r.errors}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
