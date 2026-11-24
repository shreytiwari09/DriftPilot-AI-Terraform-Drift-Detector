import FindingsTable from '../components/FindingsTable';
import { Card, Empty, Icon } from '../components/ui';
import { episodesCsv } from '../lib/logic';
import type { PageProps } from './shared';

export default function Findings({ eps, open, data }: PageProps) {
  const download = () => {
    const blob = new Blob([episodesCsv(eps)], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'driftpilot-episodes.csv';
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div><h2 className="h-page">Findings</h2><p className="text-sm text-mute">Every drift episode that matches the filters. Click a row (or press Enter) for the full story.</p></div>
        <button type="button" className="btn" onClick={download} disabled={!eps.length}><Icon name="download" /> Export CSV ({eps.length.toLocaleString('en-US')})</button>
      </div>
      <Card>
        {data.episodes.length === 0 ? <Empty title="No drift recorded yet">Nothing to list until the first scan is saved.</Empty>
          : eps.length === 0 ? <Empty title="No episodes match these filters">Widen the date range or press Reset in the filter bar.</Empty>
          : <FindingsTable rows={eps} onOpen={open} />}
      </Card>
    </div>
  );
}
