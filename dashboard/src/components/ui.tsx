import { useState, type ReactNode } from 'react';
import { safeGithubUrl } from '../lib/url';
import { SEVERITIES } from '../types';

export type IconName =
  | 'overview' | 'findings' | 'teams' | 'split' | 'shield' | 'info' | 'sun' | 'moon' | 'refresh'
  | 'external' | 'download' | 'close' | 'filter' | 'copy' | 'check' | 'play' | 'edit' | 'github'
  | 'arrow-up' | 'arrow-down' | 'search' | 'alert' | 'chevron-down' | 'pr' | 'issue' | 'compass' | 'arrow-right';

// Lucide line icons (ISC licence): 24 grid, drawn at 16px with a 1.5 stroke.
const PATHS: Record<IconName, ReactNode> = {
  overview: <><rect width="7" height="9" x="3" y="3" rx="1" /><rect width="7" height="5" x="14" y="3" rx="1" /><rect width="7" height="9" x="14" y="12" rx="1" /><rect width="7" height="5" x="3" y="16" rx="1" /></>,
  findings: <><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" /></>,
  teams: <><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" /></>,
  split: <><ellipse cx="12" cy="5" rx="9" ry="3" /><path d="M3 5v14a9 3 0 0 0 18 0V5" /><path d="M3 12a9 3 0 0 0 18 0" /></>,
  shield: <><path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z" /><path d="m9 12 2 2 4-4" /></>,
  info: <><circle cx="12" cy="12" r="10" /><path d="M12 16v-4M12 8h.01" /></>,
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2m-6.07-15.07 1.41 1.41m9.32 9.32 1.41 1.41M2 12h2m16 0h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" /></>,
  moon: <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />,
  refresh: <><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" /><path d="M21 3v5h-5" /><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" /><path d="M8 16H3v5" /></>,
  external: <><path d="M15 3h6v6M10 14 21 3" /><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /></>,
  download: <><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><path d="m7 10 5 5 5-5M12 15V3" /></>,
  close: <path d="M18 6 6 18M6 6l12 12" />,
  filter: <path d="M21 4h-7M10 4H3M21 12h-9M8 12H3M21 20h-5M12 20H3M14 2v4M8 10v4M16 18v4" />,
  copy: <><rect width="14" height="14" x="8" y="8" rx="2" /><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" /></>,
  check: <path d="M20 6 9 17l-5-5" />,
  play: <path d="M6 3l14 9-14 9V3z" />,
  edit: <><path d="M21.17 6.81a1 1 0 0 0-3.99-3.99L3.84 16.17a2 2 0 0 0-.5.83l-1.32 4.35a.5.5 0 0 0 .62.62l4.35-1.32a2 2 0 0 0 .83-.5z" /><path d="m15 5 4 4" /></>,
  github: <><path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.4 5.4 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65S8.93 17.38 9 18v4" /><path d="M9 18c-4.51 2-5-2-7-2" /></>,
  'arrow-up': <path d="m5 12 7-7 7 7M12 19V5" />,
  'arrow-down': <path d="M12 5v14m7-7-7 7-7-7" />,
  'arrow-right': <path d="M5 12h14m-7-7 7 7-7 7" />,
  search: <><circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" /></>,
  alert: <><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3" /><path d="M12 9v4M12 17h.01" /></>,
  'chevron-down': <path d="m6 9 6 6 6-6" />,
  pr: <><circle cx="18" cy="18" r="3" /><circle cx="6" cy="6" r="3" /><path d="M13 6h3a2 2 0 0 1 2 2v7M6 9v12" /></>,
  issue: <><circle cx="12" cy="12" r="10" /><circle cx="12" cy="12" r="1" /></>,
  compass: <><circle cx="12" cy="12" r="10" /><path d="m16.24 7.76-2.12 6.36-6.36 2.12 2.12-6.36 6.36-2.12z" /></>,
};

export function Icon({ name, className = 'h-4 w-4' }: { name: IconName; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={`shrink-0 ${className}`} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {PATHS[name]}
    </svg>
  );
}

const SEV_DOT: Record<string, string> = { critical: 'bg-crit', high: 'bg-high', medium: 'bg-med', low: 'bg-low' };

/** A status: small dot + text. The dot carries the meaning, the text stays in the text colours. */
export function StatusText({ dot, children }: { dot: string; children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-2 whitespace-nowrap">
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${dot}`} aria-hidden="true" />
      {children}
    </span>
  );
}

export function SeverityBadge({ severity }: { severity: string }) {
  return <StatusText dot={SEV_DOT[severity] ?? SEV_DOT.low}>{severity.charAt(0).toUpperCase() + severity.slice(1)}</StatusText>;
}

export function ResolvedStatus({ resolved }: { resolved: boolean }) {
  return <StatusText dot={resolved ? 'bg-ok' : 'bg-med'}>{resolved ? 'Resolved' : 'Open'}</StatusText>;
}

/** Counts and meta: quiet mono text on a raised surface. */
export function Tag({ children }: { children: ReactNode }) {
  return <span className="tag">{children}</span>;
}

export type MetricOrigin = 'aws' | 'driftpilot';
export const ORIGIN_LABEL: Record<MetricOrigin, string> = {
  aws: 'AWS Well-Architected',
  driftpilot: 'DriftPilot',
};

export function OriginLabel({ origin }: { origin: MetricOrigin }) {
  return <span className={origin === 'aws' ? 'text-ink' : 'text-mute'}>{ORIGIN_LABEL[origin]}</span>;
}

export function Card({ title, subtitle, action, children, className = '', flush = false }: { title?: string; subtitle?: string; action?: ReactNode; children: ReactNode; className?: string; flush?: boolean }) {
  return (
    <section className={`card ${flush ? 'overflow-hidden' : 'p-4 sm:p-5'} ${className}`}>
      {(title || action) && (
        <header className={`mb-4 flex items-start justify-between gap-3 ${flush ? 'px-4 pt-4 sm:px-5 sm:pt-5' : ''}`}>
          <div className="min-w-0">
            {title && <h2 className="h-card">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-mute">{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

/** A number, its label and what it is compared to. The longer explanation lives in a tooltip. */
export function StatCard({ label, value, detail, hint, aws, accent, bad }: { label: string; value: string; detail?: string; hint: string; aws?: boolean; accent?: boolean; bad?: boolean }) {
  return (
    <div className="card flex h-full flex-col gap-2 p-4 sm:p-5" title={hint}>
      <h3 className="text-[13px] text-ink2">
        {label}
        {aws && <sup className="ml-1 font-mono text-[11px] text-mute" aria-label="AWS Well-Architected metric">†</sup>}
      </h3>
      <p className={`fig text-[28px] font-medium leading-8 ${accent ? 'text-brand-ink' : bad ? 'text-crit' : ''}`}>{value}</p>
      <p className="text-xs text-mute">{detail ?? ' '}</p>
      <span className="sr-only">{hint}</span>
    </div>
  );
}

/** A compact figure for the quieter "Trust in DriftPilot" strip. */
export function MiniStat({ label, value, detail, hint }: { label: string; value: string; detail?: string; hint: string }) {
  return (
    <div className="min-w-0 px-4 py-3" title={hint}>
      <p className="truncate text-[13px] text-ink2">{label}</p>
      <p className="fig text-xl font-medium leading-7">{value}</p>
      <p className="truncate text-xs text-mute">{detail ?? ' '}</p>
      <span className="sr-only">{hint}</span>
    </div>
  );
}

export function Empty({ title, children, icon = 'search' }: { title: string; children?: ReactNode; icon?: IconName }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-4 py-10 text-center" role="status">
      <span className="grid h-10 w-10 place-items-center rounded-lg bg-sunken text-ink2"><Icon name={icon} /></span>
      <p className="font-medium">{title}</p>
      {children && <div className="max-w-md text-sm text-ink2">{children}</div>}
    </div>
  );
}

/** A link that leaves the dashboard. The address is checked again here, whatever called us. */
export function ExternalLink({ href, children, className = 'btn', hint, icon = 'external', label }: { href: string | null | undefined; children?: ReactNode; className?: string; hint?: string; icon?: IconName | null; label?: string }) {
  const safe = safeGithubUrl(href);
  if (!safe) return null;
  return (
    <a href={safe} target="_blank" rel="noopener noreferrer" className={className} title={hint} aria-label={label}>
      {icon && <Icon name={icon} />}
      {children}
    </a>
  );
}

/** A link button with the "what happens when I click" sentence always visible below it. */
export function ActionButton({ href, label, hint, icon }: { href: string | null | undefined; label: string; hint: string; icon: IconName }) {
  if (!safeGithubUrl(href)) return null;
  return (
    <div className="flex flex-col items-start gap-2">
      <ExternalLink href={href} icon={icon} className="btn">{label}</ExternalLink>
      <p className="hidden text-xs leading-4 text-mute sm:block">{hint}</p>
    </div>
  );
}

export function CopyButton({ text, label = 'Copy' }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const area = document.createElement('textarea'); // file:// has no clipboard API
      area.value = text;
      area.setAttribute('readonly', '');
      area.style.position = 'fixed';
      area.style.opacity = '0';
      document.body.appendChild(area);
      area.select();
      document.execCommand('copy');
      area.remove();
    }
    setDone(true);
    window.setTimeout(() => setDone(false), 1800);
  };
  return (
    <button type="button" className="btn btn-sm" onClick={() => void copy()}>
      <Icon name={done ? 'check' : 'copy'} />
      <span aria-live="polite">{done ? 'Copied' : label}</span>
    </button>
  );
}

const SEV_FILL: Record<string, string> = { critical: 'bg-crit', high: 'bg-high', medium: 'bg-med', low: 'bg-low' };

interface Ranked {
  name: string;
  value: number;
  segments?: Partial<Record<'critical' | 'high' | 'medium' | 'low', number>>;
}

/** A ranked list with thin bars: the quiet partner of the main chart. Plain HTML, so it reads as text too. */
export function RankedBars({ rows, label, valueLabel }: { rows: Ranked[]; label: string; valueLabel?: (r: Ranked) => string }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <ul aria-label={label} className="space-y-1">
      {rows.map((r) => (
        <li key={r.name} className="grid h-8 grid-cols-[minmax(72px,96px)_1fr_auto] items-center gap-3 sm:grid-cols-[minmax(72px,104px)_1fr_auto]">
          <span className="truncate text-[13px]" title={r.name}>{r.name}</span>
          <span className="flex h-1 gap-px overflow-hidden rounded-[2px] bg-ink/[0.08]" aria-hidden="true">
            {r.segments
              ? SEVERITIES.map((s) => (r.segments?.[s] ? <span key={s} className={`h-full ${SEV_FILL[s]}`} style={{ width: `${(100 * (r.segments[s] ?? 0)) / max}%` }} /> : null))
              : <span className="h-full bg-ink/40" style={{ width: `${(100 * r.value) / max}%` }} />}
          </span>
          <span className="fig min-w-[2.5rem] text-right text-xs text-mute">{valueLabel ? valueLabel(r) : r.value.toLocaleString('en-US')}</span>
        </li>
      ))}
    </ul>
  );
}
