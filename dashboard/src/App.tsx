import { useEffect, useMemo } from 'react';
import Drawer from './components/Drawer';
import FilterBar from './components/FilterBar';
import Layout from './components/Layout';
import { Empty, Icon } from './components/ui';
import { computeKpis, episodeKey, filterEpisodes } from './lib/logic';
import { periodLabel } from './lib/period';
import { buildHash, useRoute, type Page } from './lib/route';
import { useData } from './lib/useData';
import About from './pages/About';
import Findings from './pages/Findings';
import Guardrails from './pages/Guardrails';
import Overview from './pages/Overview';
import Split from './pages/Split';
import Teams from './pages/Teams';
import type { Episode, Filters } from './types';

const PAGE_COMPONENTS = { overview: Overview, findings: Findings, teams: Teams, split: Split, guardrails: Guardrails, about: About };

export default function App() {
  const state = useData();
  const { route, go } = useRoute();
  const { data } = state;

  const eps = useMemo(() => (data ? filterEpisodes(data.episodes, route.filters) : []), [data, route.filters]);
  const kpis = useMemo(() => (data ? computeKpis(data.episodes, data.runs, route.filters, data.asOf) : null), [data, route.filters]);
  const opened = useMemo(() => (data && route.open ? data.episodes.find((e) => episodeKey(e) === route.open) ?? null : null), [data, route.open]);

  useEffect(() => {
    if (data) document.title = `${data.title} · ${route.page}`;
  }, [data, route.page]);

  if (state.status === 'loading') {
    return <div className="grid min-h-screen place-items-center" role="status"><p className="text-ink2">Loading drift data…</p></div>;
  }
  if (!data || !kpis) {
    return (
      <div className="mx-auto grid min-h-screen max-w-xl place-items-center p-6">
        <div className="card w-full">
          <Empty title="Could not load the dashboard data" icon="alert">
            <p>The page could not read <code className="font-mono">data.json</code>{state.refreshError ? ` (${state.refreshError})` : ''}, and there is no embedded copy.</p>
            <p className="mt-2">If you opened the file from disk, rebuild it with <code className="font-mono">driftpilot report --html DIR</code>. If it is hosted, check that <code className="font-mono">data.json</code> sits next to <code className="font-mono">index.html</code>.</p>
            <button type="button" className="btn btn-primary mx-auto mt-4" onClick={state.refresh}><Icon name="refresh" /> Try again</button>
          </Empty>
        </div>
      </div>
    );
  }

  const setFilters = (f: Filters) => go({ filters: f, open: '' }, true);
  const open = (e: Episode) => go({ open: episodeKey(e) });
  const close = () => go({ open: '' }, true);
  const Page = PAGE_COMPONENTS[route.page];
  const hrefFor = (p: Page) => buildHash({ page: p, filters: route.filters, open: '' });

  return (
    <>
      <a href="#main" onClick={(ev) => { ev.preventDefault(); document.getElementById('main')?.focus(); }} className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[60] focus:rounded-lg focus:bg-ink focus:px-3 focus:py-2 focus:text-bg">Skip to content</a>
      <Layout page={route.page} data={data} state={state} repoFilter={route.filters.repo} period={periodLabel(route.filters, data.asOf)} hrefFor={hrefFor}>
        <FilterBar data={data} filters={route.filters} matches={eps.length} onChange={setFilters} />
        <div key={route.page}>
          <Page data={data} filters={route.filters} eps={eps} kpis={kpis} open={open} setFilters={setFilters} />
        </div>
      </Layout>
      {opened && <Drawer episode={opened} onClose={close} />}
    </>
  );
}
