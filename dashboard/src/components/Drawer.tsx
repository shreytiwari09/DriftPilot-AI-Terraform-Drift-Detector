import { useEffect, useRef, type ReactNode } from 'react';
import { dash, dateTime, hours } from '../lib/format';
import type { Episode } from '../types';
import { ActionButton, CopyButton, Icon, ResolvedStatus, SeverityBadge, Tag } from './ui';

const ACTION_TEXT: Record<string, string> = {
  revert: 'Revert: put it back as the code says',
  codify: 'Codify: change the code to match reality',
  ignore_changes: 'Ignore this setting from now on',
  investigate: 'A person should investigate',
  none: 'Nothing to do',
};

const GUARDRAIL_TEXT: Record<string, string> = {
  'never-soften': 'Never-soften guardrail: the AI tried to treat a security weakening as harmless, so DriftPilot kept it serious.',
  'suspicious-input': 'Suspicious input: the data looked like it was trying to instruct the AI, so a person must review it.',
};

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="label !mb-0.5">{label}</dt>
      <dd className="break-words text-sm">{children}</dd>
    </div>
  );
}

const SEV_RULE: Record<string, string> = { critical: 'border-crit', high: 'border-high', medium: 'border-med', low: 'border-low' };

/** The moment of the drawer: what the code says next to what is really there. */
function BeforeAfter({ e }: { e: Episode }) {
  return (
    <section aria-labelledby="d-diff">
      <h3 id="d-diff" className="h-card mb-2">Before and after</h3>
      <div className="grid gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-2">
        <div className="bg-surface p-4">
          <p className="label">Expected (before)</p>
          <code className="block whitespace-pre-wrap break-all font-mono text-[15px] leading-6 text-ink2">{e.before ?? dash}</code>
          <p className="mt-2 text-xs text-mute">What the code says</p>
        </div>
        <div className={`border-l-2 bg-surface p-4 ${SEV_RULE[e.severity] ?? SEV_RULE.low}`}>
          <p className="label">Found (after)</p>
          <code className="block whitespace-pre-wrap break-all font-mono text-[15px] leading-6 text-ink">{e.after ?? dash}</code>
          <p className="mt-2 text-xs text-mute">What is really there</p>
        </div>
      </div>
    </section>
  );
}

function Timeline({ e }: { e: Episode }) {
  const steps = [
    { label: 'First detected', when: e.start, note: undefined as string | undefined, done: true },
    ...(e.runsSeen > 1 ? [{ label: `Still there at the last of ${e.runsSeen} scans`, when: e.end, note: undefined, done: true }] : []),
    e.resolved
      ? { label: 'Resolved (first scan without it)', when: e.resolvedAt ?? e.end, note: undefined, done: true }
      : { label: 'Still open', when: null as string | null, note: 'not resolved yet', done: false },
    e.outcome !== 'pending'
      ? { label: `Human outcome: ${e.outcome}`, when: null, note: e.outcome === 'overruled' ? 'a person disagreed with DriftPilot' : 'a person agreed with DriftPilot', done: true }
      : { label: 'Human outcome: pending', when: null, note: 'nobody has reacted yet', done: false },
  ];
  return (
    <ol className="relative ml-1.5 space-y-4 border-l border-line pl-5">
      {steps.map((s) => (
        <li key={s.label} className="relative">
          <span className={`absolute -left-[26px] top-1 h-2.5 w-2.5 rounded-full border ${s.done ? 'border-ink2 bg-ink2' : 'border-mute bg-surface'}`} aria-hidden="true" />
          <p className="text-sm">{s.label}</p>
          <p className="fig text-xs text-mute">{s.when ? dateTime(s.when) : s.note}</p>
        </li>
      ))}
    </ol>
  );
}

export default function Drawer({ episode, onClose }: { episode: Episode; onClose: () => void }) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === 'Escape') onClose();
      if (ev.key !== 'Tab' || !panelRef.current) return;
      const items = panelRef.current.querySelectorAll<HTMLElement>('a[href],button:not([disabled]),[tabindex="0"]');
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (ev.shiftKey && document.activeElement === first) { ev.preventDefault(); last.focus(); }
      else if (!ev.shiftKey && document.activeElement === last) { ev.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', onKey);
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = '';
      before?.focus?.();
    };
  }, [onClose]);

  const duration = e_hours(episode);
  const guard = episode.guardrails ?? [];
  const noLinks = !episode.issueUrl && !episode.prUrl;

  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="presentation">
      <div className="fade-in absolute inset-0 bg-black/50" onClick={onClose} aria-hidden="true" />
      <div ref={panelRef} role="dialog" aria-modal="true" aria-labelledby="drawer-title" className="slide-in relative flex h-full w-full max-w-xl flex-col overflow-y-auto border-l border-line bg-surface shadow-pop sm:rounded-l-2xl">
        <header className="sticky top-0 z-10 flex items-start justify-between gap-3 border-b border-line bg-surface p-4 sm:px-5">
          <div className="min-w-0">
            <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-ink2">
              <SeverityBadge severity={episode.severity} />
              <ResolvedStatus resolved={episode.resolved} />
              <Tag>{episode.driftType}</Tag>
            </div>
            <h2 id="drawer-title" className="break-all font-mono text-sm font-medium">{episode.address}</h2>
            {episode.attribute && <p className="break-all font-mono text-xs text-mute">{episode.attribute}</p>}
          </div>
          <button ref={closeRef} type="button" className="btn btn-ghost btn-icon" onClick={onClose} aria-label="Close details"><Icon name="close" /></button>
        </header>

        <div className="space-y-6 p-4 sm:p-5">
          <section aria-labelledby="d-why">
            <h3 id="d-why" className="h-card mb-2">Why DriftPilot says so</h3>
            <p className="rounded-lg bg-sunken p-3 text-sm leading-5 text-ink2">{episode.reason || 'No reason was stored for this finding.'}</p>
            {guard.map((g) => (
              <p key={g} className="mt-2 flex gap-2 rounded-lg border border-line p-3 text-xs leading-4 text-ink2">
                <Icon name="shield" className="mt-0 h-4 w-4 shrink-0" />
                <span>{GUARDRAIL_TEXT[g] ?? `Guardrail: ${g}`}</span>
              </p>
            ))}
          </section>

          {(episode.before || episode.after) && <BeforeAfter e={episode} />}

          <dl className="grid grid-cols-2 gap-x-4 gap-y-4">
            <Field label="Decided by">{episode.decidedBy}{episode.ruleId ? ` (${episode.ruleId})` : ''}{episode.promptVersion ? ` · ${episode.promptVersion}` : ''}</Field>
            <Field label="Confidence">{typeof episode.confidence === 'number' ? `${Math.round(episode.confidence * 100)}%` : '—'}</Field>
            <Field label="Severity">{episode.severity}</Field>
            <Field label="Category">{episode.category}</Field>
            <Field label="Recommended action">{ACTION_TEXT[episode.action] ?? episode.action}</Field>
            <Field label="Human outcome">{episode.outcome}</Field>
            <Field label="Team">{episode.team}</Field>
            <Field label="Environment">{episode.environment}</Field>
            <Field label="Repo">{episode.repo}</Field>
            <Field label="Account">{episode.account}</Field>
            <Field label="Resource type">{episode.resourceType}</Field>
            <Field label="Time open">{episode.resolved ? hours(duration) : 'still open'}</Field>
          </dl>

          <section aria-labelledby="d-controls">
            <h3 id="d-controls" className="h-card mb-2">Compliance tags</h3>
            {episode.controls?.length ? (
              <div className="flex flex-wrap gap-2">{episode.controls.map((c) => <Tag key={c}>{c}</Tag>)}</div>
            ) : <p className="text-sm text-ink2">None. These tags are descriptive only (for example public-storage, least-privilege).</p>}
          </section>

          <section aria-labelledby="d-time">
            <h3 id="d-time" className="h-card mb-2">Timeline</h3>
            <Timeline e={episode} />
          </section>

          <section aria-labelledby="d-actions">
            <h3 id="d-actions" className="h-card mb-2">Take action on GitHub</h3>
            <div className="grid gap-4 sm:grid-cols-2">
              <ActionButton href={episode.issueUrl} icon="github" label="Open issue" hint="Opens the issue on GitHub in a new tab. GitHub may ask you to log in. Nothing changes until you act there." />
              <ActionButton href={episode.prUrl} icon="github" label="Open PR" hint="Opens the pull request on GitHub in a new tab. A person must review and merge it. DriftPilot never merges." />
            </div>
            {noLinks && <p className="text-sm text-ink2">No issue or pull request was opened for this finding.</p>}
          </section>

          {episode.fix && (
            <section aria-labelledby="d-fix">
              <div className="mb-2 flex items-center justify-between gap-2">
                <h3 id="d-fix" className="h-card">Suggested command to revert</h3>
                <CopyButton text={episode.fix} label="Copy" />
              </div>
              <pre tabIndex={0} className="overflow-x-auto rounded-lg bg-sunken p-3 font-mono text-xs leading-5">{episode.fix}</pre>
              <p className="mt-2 text-xs text-mute">What happens when I click Copy: the text goes to your clipboard and nothing else. It is never run by this page or by DriftPilot. You read it, then run it yourself in your own terminal, with your own login.</p>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}

function e_hours(e: Episode): number | null {
  if (!e.resolved || !e.resolvedAt) return null;
  return Math.round(((Date.parse(e.resolvedAt) - Date.parse(e.start)) / 3_600_000) * 10) / 10;
}
