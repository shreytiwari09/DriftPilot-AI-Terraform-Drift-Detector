import { useState, type ReactNode } from 'react';
import { safeGithubUrl } from '../lib/url';

export type IconName =
  | 'overview' | 'findings' | 'teams' | 'split' | 'shield' | 'info' | 'sun' | 'moon' | 'refresh'
  | 'external' | 'download' | 'close' | 'filter' | 'copy' | 'check' | 'play' | 'edit' | 'github'
  | 'arrow-up' | 'arrow-down' | 'search' | 'alert';

const PATHS: Record<IconName, ReactNode> = {
  overview: <><rect x="3" y="3" width="7" height="9" rx="1.5" /><rect x="14" y="3" width="7" height="5" rx="1.5" /><rect x="14" y="12" width="7" height="9" rx="1.5" /><rect x="3" y="16" width="7" height="5" rx="1.5" /></>,
  findings: <><path d="M4 6h16M4 12h16M4 18h10" /></>,
  teams: <><circle cx="9" cy="8" r="3.2" /><path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6" /><circle cx="17" cy="9" r="2.4" /><path d="M16.5 14.2c2.6.2 4.5 2.2 4.5 4.8" /></>,
  split: <><path d="M12 3v18" /><rect x="3" y="5" width="6" height="6" rx="1.5" /><rect x="15" y="13" width="6" height="6" rx="1.5" /></>,
  shield: <><path d="M12 3l7.5 3v5.5c0 4.4-3.1 8-7.5 9.5-4.4-1.5-7.5-5.1-7.5-9.5V6L12 3z" /><path d="M9 12l2.2 2.2L15.5 10" /></>,
  info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 8h.01" /></>,
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5L19 19M5 19l1.5-1.5M17.5 6.5L19 5" /></>,
  moon: <path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z" />,
  refresh: <><path d="M20 11a8 8 0 0 0-14.3-4.3L4 8.5" /><path d="M4 4v4.5h4.5" /><path d="M4 13a8 8 0 0 0 14.3 4.3L20 15.5" /><path d="M20 20v-4.5h-4.5" /></>,
  external: <><path d="M14 4h6v6" /><path d="M20 4l-9 9" /><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" /></>,
  download: <><path d="M12 4v11" /><path d="M7 11l5 5 5-5" /><path d="M5 20h14" /></>,
  close: <path d="M6 6l12 12M18 6L6 18" />,
  filter: <path d="M4 5h16l-6 8v6l-4-2v-4L4 5z" />,
  copy: <><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V6a2 2 0 0 1 2-2h8" /></>,
  check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
  play: <path d="M7 4.5v15l12-7.5-12-7.5z" />,
  edit: <><path d="M4 20h4L19 9l-4-4L4 16v4z" /><path d="M13.5 6.5l4 4" /></>,
  github: <path d="M12 .5a11.5 11.5 0 0 0-3.64 22.41c.58.1.79-.25.79-.56v-2c-3.2.7-3.87-1.37-3.87-1.37-.52-1.33-1.28-1.69-1.28-1.69-1.04-.71.08-.7.08-.7 1.15.08 1.76 1.18 1.76 1.18 1.03 1.76 2.69 1.25 3.35.96.1-.74.4-1.25.73-1.54-2.55-.29-5.24-1.28-5.24-5.69 0-1.26.45-2.28 1.18-3.09-.12-.29-.51-1.46.11-3.05 0 0 .97-.31 3.17 1.18a11 11 0 0 1 5.77 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.11 3.05.74.81 1.18 1.83 1.18 3.09 0 4.42-2.69 5.39-5.25 5.68.41.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56A11.5 11.5 0 0 0 12 .5z" />,
  'arrow-up': <path d="M12 19V5M6 11l6-6 6 6" />,
  'arrow-down': <path d="M12 5v14M6 13l6 6 6-6" />,
  search: <><circle cx="11" cy="11" r="6.5" /><path d="M16 16l4.5 4.5" /></>,
  alert: <><path d="M12 3l10 18H2L12 3z" /><path d="M12 10v5M12 18h.01" /></>,
};

export function Icon({ name, className = 'h-4 w-4' }: { name: IconName; className?: string }) {
  const filled = name === 'github';
  return (
    <svg viewBox="0 0 24 24" className={className} fill={filled ? 'currentColor' : 'none'} stroke={filled ? 'none' : 'currentColor'} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {PATHS[name]}
    </svg>
  );
}

const SEV_STYLE: Record<string, string> = {
  critical: 'border-crit/40 bg-crit/10 text-crit',
  high: 'border-high/40 bg-high/10 text-high',
  medium: 'border-med/40 bg-med/10 text-med',
  low: 'border-low/40 bg-low/10 text-low',
};

export function SeverityBadge({ severity }: { severity: string }) {
  return (
    <span className={`chip ${SEV_STYLE[severity] ?? SEV_STYLE.low}`}>
      <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />
      {severity}
    </span>
  );
}

export function Tag({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'neutral' | 'ok' | 'warn' | 'brand' }) {
  const tones = {
    neutral: 'border-line bg-sunken text-mute',
    ok: 'border-ok/40 bg-ok/10 text-ok',
    warn: 'border-high/40 bg-high/10 text-high',
    brand: 'border-brand/40 bg-brand/10 text-brand',
  };
  return <span className={`chip ${tones[tone]}`}>{children}</span>;
}

export type MetricOrigin = 'aws' | 'driftpilot';
export const ORIGIN_LABEL: Record<MetricOrigin, string> = {
  aws: 'AWS Well-Architected metric',
  driftpilot: 'DriftPilot metric',
};

export function OriginLabel({ origin }: { origin: MetricOrigin }) {
  return <span className={`chip !whitespace-normal text-left leading-tight ${origin === 'aws' ? 'border-brand/40 bg-brand/10 text-brand' : 'border-line bg-sunken text-mute'}`}>{ORIGIN_LABEL[origin]}</span>;
}

export function Card({ title, subtitle, action, children, className = '' }: { title?: string; subtitle?: string; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card p-4 sm:p-5 ${className}`}>
      {(title || action) && (
        <header className="mb-3 flex items-start justify-between gap-3">
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

export function KpiCard({ label, value, origin, hint, detail, tone }: { label: string; value: string; origin: MetricOrigin; hint: string; detail?: string; tone?: 'bad' | 'good' }) {
  return (
    <div className="card fade-up flex flex-col gap-1 p-3 transition hover:-translate-y-0.5 sm:p-4">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-xs font-medium text-mute sm:text-sm">{label}</h3>
      </div>
      <p className={`text-2xl font-semibold sm:text-3xl tracking-tight tabular-nums ${tone === 'bad' ? 'text-crit' : tone === 'good' ? 'text-ok' : ''}`}>{value}</p>
      {detail && <p className="text-xs text-mute">{detail}</p>}
      <p className="hidden text-xs leading-snug text-mute sm:block">{hint}</p>
      <div className="mt-1.5"><OriginLabel origin={origin} /></div>
    </div>
  );
}

export function Empty({ title, children, icon = 'search' }: { title: string; children?: ReactNode; icon?: IconName }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-4 py-10 text-center" role="status">
      <span className="grid h-11 w-11 place-items-center rounded-full bg-sunken text-mute"><Icon name={icon} className="h-5 w-5" /></span>
      <p className="font-semibold">{title}</p>
      {children && <div className="max-w-md text-sm text-mute">{children}</div>}
    </div>
  );
}

/** A link that leaves the dashboard. The address is checked again here, whatever called us. */
export function ExternalLink({ href, children, className = 'btn', hint, icon = 'external' }: { href: string | null | undefined; children: ReactNode; className?: string; hint?: string; icon?: IconName }) {
  const safe = safeGithubUrl(href);
  if (!safe) return null;
  return (
    <a href={safe} target="_blank" rel="noopener noreferrer" className={className} title={hint}>
      {icon && <Icon name={icon} />}
      {children}
    </a>
  );
}

/** A link button with the "what happens when I click" sentence always visible below it. */
export function ActionButton({ href, label, hint, icon, primary }: { href: string | null | undefined; label: string; hint: string; icon: IconName; primary?: boolean }) {
  if (!safeGithubUrl(href)) return null;
  return (
    <div className="flex flex-col gap-1">
      <ExternalLink href={href} icon={icon} className={`btn ${primary ? 'btn-primary' : ''}`}>{label}</ExternalLink>
      <p className="hidden text-xs leading-snug text-mute sm:block">{hint}</p>
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
    <button type="button" className="btn !min-h-[30px] !px-2 text-xs" onClick={() => void copy()}>
      <Icon name={done ? 'check' : 'copy'} className="h-3.5 w-3.5" />
      <span aria-live="polite">{done ? 'Copied' : label}</span>
    </button>
  );
}
