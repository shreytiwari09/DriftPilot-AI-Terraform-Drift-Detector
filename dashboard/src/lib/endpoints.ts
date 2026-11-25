// The addresses of the files published next to this page, worked out from where the page is
// served (GitHub Pages: https://<owner>.github.io/<repo>/). Opened from disk, placeholders are used.
export interface Endpoints {
  hosted: boolean;
  dataUrl: string;
  metricsUrl: string;
  host: string;
  path: string;
}

export function endpoints(href: string): Endpoints {
  let url: URL | null = null;
  try {
    url = new URL(href);
  } catch {
    url = null;
  }
  if (!url || url.protocol !== 'https:') {
    return { hosted: false, dataUrl: 'data.json', metricsUrl: 'metrics.prom', host: '<owner>.github.io', path: '/<repo>/metrics.prom' };
  }
  const dir = url.pathname.replace(/[^/]*$/, '');
  return {
    hosted: true,
    dataUrl: `${url.origin}${dir}data.json`,
    metricsUrl: `${url.origin}${dir}metrics.prom`,
    host: url.host,
    path: `${dir}metrics.prom`,
  };
}

export const prometheusConfig = (e: Endpoints): string =>
  `scrape_configs:
  - job_name: driftpilot
    scheme: https
    metrics_path: ${e.path}
    scrape_interval: 15m
    static_configs:
      - targets: ['${e.host}']`;

export const WEBHOOK_CONFIG = `notifications:
  webhook_env: DRIFTPILOT_WEBHOOK_URL
  format: slack          # or teams, generic
  min_severity: high
  on: [new_drift, monitor_alert, scan_failed]`;

export const WEBHOOK_STEP = `- uses: shreytiwari09/DriftPilot-AI-Terraform-Drift-Detector@v2
  with:
    webhook-url: \${{ secrets.DRIFTPILOT_WEBHOOK_URL }}`;

export const SARIF_COMMAND = 'driftpilot scan --sarif drift.sarif';

export const SARIF_STEP = `- uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: drift.sarif`;
