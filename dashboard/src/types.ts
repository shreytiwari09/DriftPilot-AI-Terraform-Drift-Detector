export type Severity = 'critical' | 'high' | 'medium' | 'low';
export const SEVERITIES: Severity[] = ['critical', 'high', 'medium', 'low'];

export interface Episode {
  id: string;
  address: string;
  attribute: string | null;
  resourceType: string;
  start: string;
  end: string;
  resolvedAt: string | null;
  runsSeen: number;
  severity: Severity | string;
  category: string;
  action: string;
  decidedBy: string;
  outcome: string;
  resolved: boolean;
  team: string;
  repo: string;
  environment: string;
  account: string;
  driftType: string;
  // Fields below arrived with the React dashboard; older data.json files lack them.
  reason?: string | null;
  controls?: string[];
  guardrails?: string[];
  confidence?: number | null;
  ruleId?: string | null;
  promptVersion?: string | null;
  prUrl?: string | null;
  issueUrl?: string | null;
  before?: string | null;
  after?: string | null;
  fix?: string | null;
}

export interface RunRow {
  t: string;
  repo: string;
  environment: string;
  driftType: string;
  dir: string;
  managed: number | null;
  unmanaged: number;
  managedByTeam: Record<string, number>;
  unmanagedByTeam: Record<string, number>;
}

export interface Kpis {
  episodes: number;
  managed: number | null;
  unmanaged: number | null;
  driftedResources: number;
  iacCoverage: number | null;
  driftRate: number | null;
  openCount: number;
  oldestOpenHours: number | null;
  mttrHours: number | null;
  decided: number;
  overruleRate: number | null;
  alertPrecision: number | null;
  recurringOffenders: number;
}

export interface Filters {
  from: string;
  to: string;
  team: string;
  repo: string;
  environment: string;
  driftType: string;
  severity: string;
  status: string;
  decidedBy: string;
  outcome: string;
  search: string;
}

export const FILTER_KEYS: (keyof Filters)[] = [
  'from', 'to', 'team', 'repo', 'environment', 'driftType', 'severity', 'status', 'decidedBy',
  'outcome', 'search',
];

export interface AuditRun {
  runId: string;
  t: string;
  repo: string;
  environment: string;
  driftType: string;
  calls: number;
  invalid: number;
  events: Record<string, number>;
}

export interface Links {
  repo: string | null;
  workflow: string | null;
  branch: string | null;
}

export interface RecentRun {
  t: string;
  findings: number;
  critical: number;
  noise: number;
  errors: number;
}

/** One stream of scans: a repo, environment, drift type and folder. Counts are as of the latest scan in the data. */
export interface ScanStream {
  repo: string;
  environment: string;
  driftType: string;
  dir: string;
  lastRun: string;
  runCount24h: number;
  runCount7d: number;
  longestGapHours7d: number;
  errors7d: number;
  recent: RecentRun[];
}

export interface ScanHealth {
  expectedHours: number;
  streams: ScanStream[];
}

export type SlaHours = Partial<Record<string, number | null>>;

export interface Ratio {
  hits: number;
  total: number;
}

export interface AttackRow {
  setup: string;
  attackSuccess: Ratio;
  softerOnly: Ratio;
  neverSoften: Ratio;
  benignRight: Ratio;
  llmCalls: number;
}

export interface EvaluationSummary {
  date: string | null;
  model: string;
  caveat?: string;
  main: { findings: number; real: number };
  adversarial: { cases: number; attackCases: number; benignCases: number; withoutGuardrails: AttackRow; withGuardrails: AttackRow };
  database: { findings: number; real: number };
}

export interface DashboardData {
  schema: number;
  title: string;
  note: string | null;
  generated: string | null;
  asOf: string | null;
  periodStart: string | null;
  periodEnd: string | null;
  publishAddresses: boolean;
  episodes: Episode[];
  runs: RunRow[];
  kpis: Kpis;
  analytics: {
    days: string[];
    daily: number[];
    anomalies: (number | null)[];
    changePoints: string[];
    recurring: { address: string; attribute: string | null; episodes: number }[];
    dayAnomalies: { day: string; newEpisodes: number; usual: number; z: number }[];
    shifts: { dimension: string; psi: number; chi2p: number; shifted: boolean }[];
    health: Record<string, number | null>;
  };
  links?: Links;
  guardrails?: { llmCallLimit: number | null; hasAudit: boolean; runs: AuditRun[] };
  // Added with the observability release; older data.json files lack them.
  scans?: ScanHealth;
  sla?: SlaHours;
  evaluation?: EvaluationSummary;
  monitor: {
    alerts: string[];
    overruleThreshold: number;
    recentOverruleRate: number | null;
    baselineOverruleRate: number | null;
  };
}
