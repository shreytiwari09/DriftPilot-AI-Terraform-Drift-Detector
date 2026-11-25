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
    <div className="stagger space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-[13px] text-ink2">Select a row (or press Enter) for the full story</p>
        <button type="button" className="btn" onClick={download} disabled={!eps.length}><Icon name="download" /> Export CSV <span className="fig text-mute">{eps.length.toLocaleString('en-US')}</span></button>
      </div>
      <Card flush>
        {data.episodes.length === 0 ? <Empty title="No drift recorded yet">Nothing to list until the first scan is saved.</Empty>
          : eps.length === 0 ? <Empty title="No episodes match these filters">Widen the date range or press Reset in the filter bar.</Empty>
          : <FindingsTable rows={eps} onOpen={open} />}
      </Card>
    </div>
  );
}
