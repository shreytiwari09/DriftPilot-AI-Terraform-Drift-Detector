import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { shortDate } from '../lib/format';
import { palette, useTheme } from '../lib/theme';
import { SEVERITIES } from '../types';

const reduced = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;

function useChart() {
  const { dark } = useTheme();
  const c = palette(dark);
  const tooltip = {
    contentStyle: { background: c.surface, border: `1px solid ${c.grid}`, borderRadius: 10, fontSize: 12, color: dark ? '#e6edf7' : '#0f172a' },
    labelStyle: { fontWeight: 600 },
    cursor: { fill: dark ? 'rgba(148,163,184,0.12)' : 'rgba(100,116,139,0.1)' },
  };
  return { c, tooltip, animate: !reduced(), tick: { fill: c.text, fontSize: 11 } };
}

const sevColor = (c: ReturnType<typeof palette>, s: string) => c[s as 'critical'] ?? c.low;

export function ChartFrame({ label, height = 260, children }: { label: string; height?: number; children: React.ReactElement }) {
  return (
    <div role="img" aria-label={label} style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">{children}</ResponsiveContainer>
    </div>
  );
}

export function DailyChart({ rows }: { rows: Record<string, number | string>[] }) {
  const { c, tooltip, animate, tick } = useChart();
  const total = rows.reduce((a, r) => a + SEVERITIES.reduce((b, s) => b + (Number(r[s]) || 0), 0), 0);
  return (
    <ChartFrame label={`Bar chart of new drift episodes per day by severity, ${total} in total`}>
      <BarChart data={rows} margin={{ top: 6, right: 8, left: -18, bottom: 0 }}>
        <CartesianGrid stroke={c.grid} vertical={false} />
        <XAxis dataKey="day" tick={tick} tickFormatter={shortDate} minTickGap={28} axisLine={false} tickLine={false} />
        <YAxis allowDecimals={false} tick={tick} axisLine={false} tickLine={false} />
        <Tooltip {...tooltip} labelFormatter={(d) => shortDate(String(d))} />
        <Legend wrapperStyle={{ fontSize: 12, color: c.text }} iconType="circle" />
        {[...SEVERITIES].reverse().map((s) => (
          <Bar key={s} dataKey={s} stackId="sev" fill={sevColor(c, s)} isAnimationActive={animate} maxBarSize={18} />
        ))}
      </BarChart>
    </ChartFrame>
  );
}

export function StackedHBars({ rows, label }: { rows: { name: string; critical?: number; high?: number; medium?: number; low?: number }[]; label: string }) {
  const { c, tooltip, animate, tick } = useChart();
  const height = Math.max(180, rows.length * 38 + 50);
  return (
    <ChartFrame label={label} height={height}>
      <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 12, left: 4, bottom: 0 }}>
        <CartesianGrid stroke={c.grid} horizontal={false} />
        <XAxis type="number" allowDecimals={false} tick={tick} axisLine={false} tickLine={false} />
        <YAxis type="category" dataKey="name" width={86} tick={tick} axisLine={false} tickLine={false} />
        <Tooltip {...tooltip} />
        <Legend wrapperStyle={{ fontSize: 12, color: c.text }} iconType="circle" />
        {[...SEVERITIES].reverse().map((s) => (
          <Bar key={s} dataKey={s} stackId="sev" fill={sevColor(c, s)} isAnimationActive={animate} maxBarSize={22} />
        ))}
      </BarChart>
    </ChartFrame>
  );
}

export function Donut({ rows, label }: { rows: { name: string; value: number }[]; label: string }) {
  const { c, tooltip, animate } = useChart();
  const colors = [c.brand, c.teal, c.high, c.medium];
  const total = rows.reduce((a, r) => a + r.value, 0);
  return (
    <ChartFrame label={label} height={230}>
      <PieChart>
        <Pie data={rows} dataKey="value" nameKey="name" innerRadius="58%" outerRadius="85%" paddingAngle={2} stroke={c.surface} isAnimationActive={animate}>
          {rows.map((r, i) => <Cell key={r.name} fill={colors[i % colors.length]} />)}
        </Pie>
        <Tooltip {...tooltip} formatter={(v: number, n: string) => [`${v} (${total ? Math.round((100 * v) / total) : 0}%)`, n]} />
        <Legend wrapperStyle={{ fontSize: 12, color: c.text }} iconType="circle" />
      </PieChart>
    </ChartFrame>
  );
}

export function OverruleTrend({ rows, threshold }: { rows: { week: string; rate: number; decided: number }[]; threshold: number }) {
  const { c, tooltip, animate, tick } = useChart();
  return (
    <ChartFrame label="Line chart of the weekly share of drift findings that people overruled">
      <LineChart data={rows} margin={{ top: 6, right: 8, left: -14, bottom: 0 }}>
        <CartesianGrid stroke={c.grid} vertical={false} />
        <XAxis dataKey="week" tick={tick} tickFormatter={shortDate} minTickGap={28} axisLine={false} tickLine={false} />
        <YAxis domain={[0, 100]} unit="%" tick={tick} axisLine={false} tickLine={false} />
        <Tooltip {...tooltip} labelFormatter={(d) => `Week of ${shortDate(String(d))}`} formatter={(v: number, _n, item) => [`${v}% of ${item.payload.decided} decided`, 'Overruled']} />
        <ReferenceLine y={threshold} stroke={c.critical} strokeDasharray="4 4" label={{ value: `alert at ${threshold}%`, fill: c.critical, fontSize: 11, position: 'insideTopRight' }} />
        <Line type="linear" dataKey="rate" stroke={c.brand} strokeWidth={2.5} dot={{ r: 3, fill: c.brand }} isAnimationActive={animate} />
      </LineChart>
    </ChartFrame>
  );
}

export function CallsChart({ rows, limit }: { rows: { name: string; calls: number; invalid: number }[]; limit: number | null }) {
  const { c, tooltip, animate, tick } = useChart();
  return (
    <ChartFrame label={`Bar chart of LLM calls per run${limit ? `, budget ${limit} per run` : ''}`}>
      <BarChart data={rows} margin={{ top: 10, right: 8, left: -18, bottom: 0 }}>
        <CartesianGrid stroke={c.grid} vertical={false} />
        <XAxis dataKey="name" tick={tick} tickFormatter={shortDate} minTickGap={28} axisLine={false} tickLine={false} />
        <YAxis allowDecimals={false} tick={tick} axisLine={false} tickLine={false} domain={[0, (max: number) => Math.max(max, limit ?? 0)]} />
        <Tooltip {...tooltip} labelFormatter={(d) => shortDate(String(d))} />
        {limit ? <ReferenceLine y={limit} stroke={c.critical} strokeDasharray="4 4" label={{ value: `budget ${limit}`, fill: c.critical, fontSize: 11, position: 'insideTopRight' }} /> : null}
        <Bar dataKey="calls" name="LLM calls" fill={c.brand} isAnimationActive={animate} maxBarSize={14} radius={[3, 3, 0, 0]} />
      </BarChart>
    </ChartFrame>
  );
}

export function GroupedBars({ rows, keys, label }: { rows: Record<string, number | string>[]; keys: { key: string; name: string; color: 'brand' | 'teal' }[]; label: string }) {
  const { c, tooltip, animate, tick } = useChart();
  return (
    <ChartFrame label={label}>
      <BarChart data={rows} margin={{ top: 6, right: 8, left: -18, bottom: 0 }}>
        <CartesianGrid stroke={c.grid} vertical={false} />
        <XAxis dataKey="day" tick={tick} tickFormatter={shortDate} minTickGap={28} axisLine={false} tickLine={false} />
        <YAxis allowDecimals={false} tick={tick} axisLine={false} tickLine={false} />
        <Tooltip {...tooltip} labelFormatter={(d) => shortDate(String(d))} />
        <Legend wrapperStyle={{ fontSize: 12, color: c.text }} iconType="circle" />
        {keys.map((k) => <Bar key={k.key} dataKey={k.key} name={k.name} stackId="t" fill={c[k.color]} isAnimationActive={animate} maxBarSize={18} />)}
      </BarChart>
    </ChartFrame>
  );
}
