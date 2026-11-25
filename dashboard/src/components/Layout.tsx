import { useEffect, useState, type ReactNode } from 'react';
import { dateTime } from '../lib/format';
import { scanLamp, type LampTone } from '../lib/lamp';
import { PAGES, type Page } from '../lib/route';
import { useTheme } from '../lib/theme';
import { actionLinks } from '../lib/url';
import type { DataState } from '../lib/useData';
import type { DashboardData } from '../types';
import { ExternalLink, Icon, type IconName } from './ui';

const NAV: Record<Page, { label: string; title: string; icon: IconName }> = {
  overview: { label: 'Overview', title: 'Overview', icon: 'overview' },
  findings: { label: 'Findings', title: 'Findings', icon: 'findings' },
  teams: { label: 'Teams', title: 'Teams', icon: 'teams' },
  split: { label: 'Infra vs Database', title: 'Infrastructure vs database', icon: 'split' },
  guardrails: { label: 'Guardrails', title: 'Guardrails', icon: 'shield' },
  about: { label: 'About', title: 'About', icon: 'info' },
};

const LAMP_DOT: Record<LampTone, string> = { fresh: 'bg-ok', aging: 'bg-low', stale: 'bg-med', simulated: 'bg-low' };

interface Props {
  page: Page;
  data: DashboardData;
  state: DataState;
  repoFilter: string;
  period: string;
  hrefFor: (p: Page) => string;
  children: ReactNode;
}

/** The product mark: a flat compass glyph and the name, one solid colour. */
function Logo({ className = '' }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2 text-ink ${className}`}>
      <Icon name="compass" className="h-5 w-5" />
      <span className="text-base font-medium leading-none">DriftPilot</span>
    </span>
  );
}

function NavLink({ p, page, href, mobile }: { p: Page; page: Page; href: string; mobile?: boolean }) {
  const on = p === page;
  return (
    <a href={href} aria-current={on ? 'page' : undefined}
      className={`flex h-9 shrink-0 items-center gap-2 rounded-lg px-3 text-sm transition-colors ${on ? `bg-sunken font-medium text-brand-ink ${mobile ? '' : 'shadow-[inset_0_1px_0_rgb(255_255_255/0.06)]'}` : 'text-ink2 hover:bg-sunken hover:text-ink'}`}>
      <span className="grid h-5 w-5 place-items-center"><Icon name={NAV[p].icon} /></span>
      {NAV[p].label}
    </a>
  );
}

export default function Layout({ page, data, state, repoFilter, period, hrefFor, children }: Props) {
  const { dark, toggle } = useTheme();
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const t = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(t);
  }, []);
  const links = actionLinks(data.links, repoFilter);
  const lamp = scanLamp(data.generated, data.note, now);
  const lampTitle = `Data generated ${dateTime(data.generated)}${data.asOf ? `. Latest scan in it: ${dateTime(data.asOf)}` : ''}${state.source === 'embedded' ? '. Showing the embedded copy' : ''}`;

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[240px_1fr]">
      <aside className="hidden border-r border-line bg-side lg:block">
        <div className="sticky top-0 flex h-screen flex-col p-4">
          <a href="#/overview" aria-label="DriftPilot home" className="mb-6 flex h-9 items-center px-3"><Logo /></a>
          <nav aria-label="Pages" className="flex flex-col gap-0.5">
            {PAGES.map((p) => <NavLink key={p} p={p} page={page} href={hrefFor(p)} />)}
          </nav>
          <p className="mt-auto px-3 text-xs leading-4 text-mute">Read-only. Reads <span className="font-mono">data.json</span> and refreshes every 5 minutes</p>
        </div>
      </aside>

      <div className="min-w-0">
        <div className="lg:hidden">
          <div className="flex h-12 items-center px-4"><a href="#/overview" aria-label="DriftPilot home"><Logo /></a></div>
          <nav aria-label="Pages" className="scroll-x flex gap-0.5 px-3 pb-2">
            {PAGES.map((p) => <NavLink key={p} p={p} page={page} href={hrefFor(p)} mobile />)}
          </nav>
        </div>
        <div className="mx-auto max-w-[1440px] px-4 pb-10 pt-4 sm:px-6 lg:px-8 lg:pt-8">
          <header className="mb-6 flex flex-wrap items-start justify-between gap-x-4 gap-y-4">
            <div className="min-w-0">
              <div className="flex flex-wrap items-baseline gap-x-3">
                <h1 className="h-page">{NAV[page].title}</h1>
                <span className="fig text-[13px] text-mute">{period}</span>
              </div>
              <p className="mt-1 inline-flex items-center gap-2 font-mono text-xs text-ink2" title={lampTitle}>
                <span className={`h-2 w-2 rounded-full ${LAMP_DOT[lamp.tone]}`} aria-hidden="true" />
                {lamp.label}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <ExternalLink href={links.scan} className="btn btn-primary" icon="play" hint="Run a scan now: opens this repo's workflow page on GitHub. GitHub asks you to log in; click its own 'Run workflow' button there. DriftPilot itself changes nothing.">
                Run a scan now
              </ExternalLink>
              <ExternalLink href={links.settings} className="btn btn-ghost" icon="edit" hint="Edit settings: opens .driftpilot.yml on GitHub in edit mode. GitHub asks you to log in; the change is a normal commit you review.">
                <span className="hidden md:inline">Edit settings</span><span className="sr-only md:hidden">Edit settings</span>
              </ExternalLink>
              <ExternalLink href={links.source} className="btn btn-ghost" icon="github" hint="Source repo: opens the repository on GitHub in a new tab.">
                <span className="hidden md:inline">Source repo</span><span className="sr-only md:hidden">Source repo</span>
              </ExternalLink>
              <button type="button" className="btn btn-ghost btn-icon tip" onClick={state.refresh} aria-label="Refresh data" data-tip="Refresh data"><Icon name="refresh" /></button>
              <button type="button" className="btn btn-ghost btn-icon tip" onClick={toggle} aria-label={dark ? 'Switch to light theme' : 'Switch to dark theme'} aria-pressed={dark} data-tip={dark ? 'Light theme' : 'Dark theme'}><Icon name={dark ? 'sun' : 'moon'} /></button>
            </div>
          </header>
          {state.refreshError && state.status === 'ready' && state.source !== 'embedded' && (
            <p role="alert" className="mb-4 flex items-center gap-2 rounded-lg border border-line bg-sunken px-3 py-2 text-sm"><Icon name="alert" className="h-4 w-4 text-med" /> Could not refresh data.json ({state.refreshError}). Showing the last data that loaded.</p>
          )}
          {data.note && <p className="mb-4 text-xs text-mute">{data.note.replace(/\.\s*$/, '')}</p>}
          <main id="main" tabIndex={-1}>{children}</main>
        </div>
      </div>
    </div>
  );
}
