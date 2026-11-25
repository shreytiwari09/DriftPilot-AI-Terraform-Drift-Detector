import { Bar, BarChart, CartesianGrid, Line, LineChart, ReferenceDot, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { shortDate } from '../lib/format';
import { palette, useTheme } from '../lib/theme';
import { SEVERITIES, type Severity } from '../types';

const reduced = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
const MONO = '"IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace';

function useChart() {
  const { dark } = useTheme();
  const c = palette(dark);
  return { c, animate: !reduced(), tick: { fill: c.text, fontSize: 11, fontFamily: MONO }, cursor: { fill: c.cursor } };
}

const sevColor = (c: ReturnType<typeof palette>, s: string) => c[s as 'critical'] ?? c.low;
const SEV_LABEL: Record<string, string> = { critical: 'Critical', high: 'High', medium: 'Medium', low: 'Low' };

export function ChartFrame({ label, height = 280, children }: { label: string; height?: number; children: React.ReactElement }) {
  return (
    <div role="img" aria-label={label} style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">{children}</ResponsiveContainer>
    </div>
  );
}

interface TipItem { dataKey?: string | number; name?: string | number; value?: number | string; color?: string; payload?: Record<string, unknown> }

/** The tooltip, drawn in the palette: raised surface, hairline, mono figures. */
function Tip({ active, payload, label, title, total, line }: { active?: boolean; payload?: TipItem[]; label?: string | number; title: (l: string) => string; total?: boolean; line?: (item: TipItem) => string }) {
  if (!active || !payload?.length) return null;
  const items = [...payload].reverse();
  const sum = items.reduce((a, i) => a + (Number(i.value) || 0), 0);
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-pop dark:bg-sunken">
      <p className="mb-1 font-medium">{title(String(label))}</p>
      <ul className="space-y-0.5">
        {items.map((i) => (
          <li key={String(i.dataKey)} className="flex items-center gap-2 text-ink2">
            <span className="h-1.5 w-1.5 rounded-full" style={{ background: i.color }} aria-hidden="true" />
            <span className="flex-1">{SEV_LABEL[String(i.dataKey)] ?? i.name}</span>
            <span className="fig text-ink">{line ? line(i) : Number(i.value).toLocaleString('en-US')}</span>
          </li>
        ))}
      </ul>
      {total && items.length > 1 && <p className="mt-1 flex justify-between border-t border-line pt-1 text-ink2"><span>Total</span><span className="fig text-ink">{sum}</span></p>}
    </div>
  );
}

/** Severity names with their counts in the period: the legend, set directly above the chart. */
export function SeverityLegend({ totals }: { totals: Record<Severity, number> }) {
  const { dark } = useTheme();
  const c = palette(dark);
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink2" aria-label="Severity legend">
      {SEVERITIES.map((s) => (
        <li key={s} className="flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full" style={{ background: sevColor(c, s) }} aria-hidden="true" />
          {SEV_LABEL[s]} <span className="fig text-mute">{totals[s]}</span>
        </li>
      ))}
    </ul>
  );
}

export function severityTotals(rows: Record<string, number | string>[]): Record<Severity, number> {
  const t: Record<Severity, number> = { critical: 0, high: 0, medium: 0, low: 0 };
  for (const r of rows) for (const s of SEVERITIES) t[s] += Number(r[s]) || 0;
  return t;
}

/** THE main chart: new drift episodes per day, stacked by severity. */
export function DailyChart({ rows, height = 320 }: { rows: Record<string, number | string>[]; height?: number }) {
  const { c, animate, tick, cursor } = useChart();
  const sums = rows.map((r) => ({ day: String(r.day), total: SEVERITIES.reduce((b, s) => b + (Number(r[s]) || 0), 0) }));
  const total = sums.reduce((a, r) => a + r.total, 0);
  const peak = sums.reduce((m, r) => (r.total > m.total ? r : m), { day: '', total: 0 });
  return (
    <ChartFrame label={`Bar chart of new drift episodes per day by severity, ${total} in total`} height={height}>
      <BarChart data={rows} margin={{ top: 24, right: 0, left: 0, bottom: 0 }} barCategoryGap="12%">
        <CartesianGrid stroke={c.grid} vertical={false} />
        <XAxis dataKey="day" tick={tick} tickFormatter={shortDate} minTickGap={40} tickMargin={8} axisLine={{ stroke: c.grid }} tickLine={false} />
        <YAxis allowDecimals={false} tick={tick} width={32} tickMargin={4} axisLine={false} tickLine={false} />
        <Tooltip cursor={cursor} content={<Tip title={(d) => shortDate(d)} total />} />
        {[...SEVERITIES].reverse().map((s) => (
          <Bar key={s} dataKey={s} stackId="sev" fill={sevColor(c, s)} stroke={c.surface} strokeWidth={0.75} isAnimationActive={animate} maxBarSize={14} />
        ))}
        {peak.total > 0 && (
          <ReferenceDot x={peak.day} y={peak.total} r={0} ifOverflow="extendDomain" label={{ value: `${peak.total} on ${shortDate(peak.day)}`, position: 'top', fill: c.text, fontSize: 11, fontFamily: MONO }} />
        )}
      </BarChart>
    </ChartFrame>
  );
}

export function OverruleTrend({ rows, threshold }: { rows: { week: string; rate: number; decided: number }[]; threshold: number }) {
  const { c, animate, tick } = useChart();
  return (
    <ChartFrame label="Line chart of the weekly share of drift findings that people overruled" height={220}>
      <LineChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid stroke={c.grid} vertical={false} />
        <XAxis dataKey="week" tick={tick} tickFormatter={shortDate} minTickGap={40} tickMargin={8} axisLine={{ stroke: c.grid }} tickLine={false} />
        <YAxis domain={[0, 100]} ticks={[0, 50, 100]} unit="%" tick={tick} width={36} tickMargin={4} axisLine={false} tickLine={false} />
        <Tooltip cursor={{ stroke: c.grid }} content={<Tip title={(d) => `Week of ${shortDate(d)}`} line={(i) => `${i.value}% of ${i.payload?.decided} decided`} />} />
        <ReferenceLine y={threshold} stroke={c.critical} strokeOpacity={0.6} strokeDasharray="4 4" label={{ value: `alert ${threshold}%`, fill: c.text, fontSize: 11, fontFamily: MONO, position: 'insideBottomRight' }} />
        <Line type="linear" name="Overruled" dataKey="rate" stroke={c.brand} strokeWidth={2} dot={{ r: 2.5, fill: c.brand, strokeWidth: 0 }} activeDot={{ r: 4 }} isAnimationActive={animate} />
      </LineChart>
    </ChartFrame>
  );
}

export function CallsChart({ rows, limit, height = 300 }: { rows: { name: string; calls: number; invalid: number }[]; limit: number | null; height?: number }) {
  const { c, animate, tick, cursor } = useChart();
  return (
    <ChartFrame label={`Bar chart of LLM calls per run${limit ? `, budget ${limit} per run` : ''}`} height={height}>
      <BarChart data={rows} margin={{ top: 12, right: 0, left: 0, bottom: 0 }}>
        <CartesianGrid stroke={c.grid} vertical={false} />
        <XAxis dataKey="name" tick={tick} tickFormatter={shortDate} minTickGap={40} tickMargin={8} axisLine={{ stroke: c.grid }} tickLine={false} />
        <YAxis allowDecimals={false} tick={tick} width={32} tickMargin={4} axisLine={false} tickLine={false} domain={[0, (max: number) => Math.max(max, limit ?? 0)]} />
        <Tooltip cursor={cursor} content={<Tip title={(d) => shortDate(d)} />} />
        {limit ? <ReferenceLine y={limit} stroke={c.critical} strokeOpacity={0.6} strokeDasharray="4 4" label={{ value: `budget ${limit}`, fill: c.text, fontSize: 11, fontFamily: MONO, position: 'insideTopRight' }} /> : null}
        <Bar dataKey="calls" name="LLM calls" fill={c.brand} isAnimationActive={animate} maxBarSize={12} />
      </BarChart>
    </ChartFrame>
  );
}

/** Two series that both matter: the first leads in the accent, the second sits in a neutral step. */
export function GroupedBars({ rows, keys, label, height = 320 }: { rows: Record<string, number | string>[]; keys: { key: string; name: string; color: 'brand' | 'neutral' }[]; label: string; height?: number }) {
  const { c, animate, tick, cursor } = useChart();
  return (
    <ChartFrame label={label} height={height}>
      <BarChart data={rows} margin={{ top: 12, right: 0, left: 0, bottom: 0 }} barCategoryGap="12%">
        <CartesianGrid stroke={c.grid} vertical={false} />
        <XAxis dataKey="day" tick={tick} tickFormatter={shortDate} minTickGap={40} tickMargin={8} axisLine={{ stroke: c.grid }} tickLine={false} />
        <YAxis allowDecimals={false} tick={tick} width={32} tickMargin={4} axisLine={false} tickLine={false} />
        <Tooltip cursor={cursor} content={<Tip title={(d) => shortDate(d)} total />} />
        {keys.map((k) => <Bar key={k.key} dataKey={k.key} name={k.name} stackId="t" fill={c[k.color]} stroke={c.surface} strokeWidth={0.75} isAnimationActive={animate} maxBarSize={14} />)}
      </BarChart>
    </ChartFrame>
  );
}
