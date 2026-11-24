import { useEffect, useState, type ReactNode } from 'react';
import { ago, dateTime } from '../lib/format';
import { PAGES, type Page } from '../lib/route';
import { useTheme } from '../lib/theme';
import { actionLinks } from '../lib/url';
import type { DataState } from '../lib/useData';
import type { DashboardData } from '../types';
import { ExternalLink, Icon, type IconName } from './ui';

const NAV: Record<Page, { label: string; icon: IconName }> = {
  overview: { label: 'Overview', icon: 'overview' },
  findings: { label: 'Findings', icon: 'findings' },
  teams: { label: 'Teams', icon: 'teams' },
  split: { label: 'Infra vs Database', icon: 'split' },
  guardrails: { label: 'Guardrails', icon: 'shield' },
  about: { label: 'About', icon: 'info' },
};

interface Props {
  page: Page;
  data: DashboardData;
  state: DataState;
  repoFilter: string;
  hrefFor: (p: Page) => string;
  children: ReactNode;
}

export default function Layout({ page, data, state, repoFilter, hrefFor, children }: Props) {
  const { dark, toggle } = useTheme();
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const t = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(t);
  }, []);
  const links = actionLinks(data.links, repoFilter);

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[232px_1fr]">
      <aside className="hidden border-r border-line bg-surface lg:block">
        <div className="sticky top-0 flex h-screen flex-col gap-6 p-4">
          <a href="#/overview" aria-label="DriftPilot home"><img src="./logo.svg" alt="DriftPilot" className="h-9 w-auto" /></a>
          <nav aria-label="Pages" className="flex flex-col gap-1">
            {PAGES.map((p) => (
              <a key={p} href={hrefFor(p)} aria-current={p === page ? 'page' : undefined}
                className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition ${p === page ? 'bg-brand/10 text-brand' : 'text-mute hover:bg-sunken hover:text-ink'}`}>
                <Icon name={NAV[p].icon} className="h-[18px] w-[18px]" /> {NAV[p].label}
              </a>
            ))}
          </nav>
          <p className="mt-auto text-xs leading-relaxed text-mute">Reads <code className="font-mono">data.json</code>, refreshes every 5 minutes. Read-only: this page never changes your infrastructure.</p>
        </div>
      </aside>

      <div className="min-w-0">
        <header className="sticky top-0 z-30 border-b border-line bg-bg/85 backdrop-blur">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2.5 sm:px-6">
            <a href="#/overview" className="lg:hidden" aria-label="DriftPilot home"><img src="./favicon.svg" alt="" className="h-8 w-8" /></a>
            <div className="min-w-0 basis-[calc(100%-44px)] sm:flex-1 sm:basis-0">
              <h1 className="truncate text-sm font-semibold sm:text-base">{data.title}</h1>
              <p className="truncate text-xs text-mute">
                {data.asOf ? <>Data up to {dateTime(data.asOf)}</> : 'No scans recorded yet'}
                {' · '}checked {ago(state.checkedAt, now)}
                {state.source === 'embedded' && ' · embedded copy'}
              </p>
            </div>
            <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
              <ExternalLink href={links.scan} className="btn btn-primary" icon="play" hint="Run a scan now: opens this repo's workflow page on GitHub. GitHub asks you to log in; click its own 'Run workflow' button there. DriftPilot itself changes nothing.">
                <span className="hidden sm:inline">Run a scan now</span><span className="sm:hidden">Scan</span>
              </ExternalLink>
              <ExternalLink href={links.settings} icon="edit" hint="Edit settings: opens .driftpilot.yml on GitHub in edit mode. GitHub asks you to log in; the change is a normal commit you review.">
                <span className="hidden md:inline">Edit settings</span><span className="md:hidden sr-only">Edit settings</span>
              </ExternalLink>
              <ExternalLink href={links.source} icon="github" hint="Dashboard source repo: opens the repository on GitHub in a new tab.">
                <span className="hidden md:inline">Source repo</span><span className="md:hidden sr-only">Source repo</span>
              </ExternalLink>
              <button type="button" className="btn !px-2.5" onClick={state.refresh} aria-label="Refresh data now" title="Refresh data now"><Icon name="refresh" /></button>
              <button type="button" className="btn !px-2.5" onClick={toggle} aria-label={dark ? 'Switch to light theme' : 'Switch to dark theme'} aria-pressed={dark} title="Light / dark"><Icon name={dark ? 'sun' : 'moon'} /></button>
            </div>
          </div>
          <nav aria-label="Pages" className="scroll-x flex gap-1 px-3 pb-2 lg:hidden">
            {PAGES.map((p) => (
              <a key={p} href={hrefFor(p)} aria-current={p === page ? 'page' : undefined}
                className={`flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium ${p === page ? 'bg-brand/10 text-brand' : 'text-mute'}`}>
                <Icon name={NAV[p].icon} className="h-4 w-4" /> {NAV[p].label}
              </a>
            ))}
          </nav>
        </header>
        {state.refreshError && state.status === 'ready' && state.source !== 'embedded' && (
          <p role="alert" className="mx-4 mt-3 flex items-center gap-2 rounded-lg border border-high/40 bg-high/10 px-3 py-2 text-sm sm:mx-6"><Icon name="alert" className="h-4 w-4 text-high" /> Could not refresh data.json ({state.refreshError}). Showing the last data that loaded.</p>
        )}
        {data.note && <p className="mx-4 mt-3 rounded-lg border border-brand/30 bg-brand/10 px-3 py-2 text-sm sm:mx-6">{data.note}</p>}
        <main id="main" className="px-4 py-5 sm:px-6" tabIndex={-1}>{children}</main>
      </div>
    </div>
  );
}
