// Every link on the page that leaves the dashboard goes through here. Only plain
// https://github.com links survive, so a `javascript:` URL or a look-alike host can never
// become a button. (Python's safe_github_url in report/dashboard/data.py is the twin.)
import type { Links } from '../types';

const GITHUB_URL = /^https:\/\/github\.com(\/[A-Za-z0-9._~/%#?&=+-]*)?$/;
const REPO = /^[\w.-]+\/[\w.-]+$/;
const WORKFLOW = /^[\w.-]+\.ya?ml$/;
const BRANCH = /^\w[\w./-]*$/;

export function safeGithubUrl(url: unknown): string | null {
  return typeof url === 'string' && url.length <= 300 && GITHUB_URL.test(url) ? url : null;
}

export interface ActionLinks {
  scan: string | null;
  settings: string | null;
  source: string | null;
}

/** The buttons' targets. `repoOverride` is the repo chosen in the filter bar, if it looks like owner/name. */
export function actionLinks(links: Links | undefined, repoOverride = ''): ActionLinks {
  const repo = [repoOverride, links?.repo].find((r) => r && REPO.test(r) && !r.includes('..')) ?? null;
  const workflow = links?.workflow && WORKFLOW.test(links.workflow) ? links.workflow : null;
  const branch = links?.branch && BRANCH.test(links.branch) && !links.branch.includes('..') ? links.branch : null;
  return {
    scan: repo && workflow ? safeGithubUrl(`https://github.com/${repo}/actions/workflows/${workflow}`) : null,
    settings: repo && branch ? safeGithubUrl(`https://github.com/${repo}/edit/${branch}/.driftpilot.yml`) : null,
    source: repo ? safeGithubUrl(`https://github.com/${repo}`) : null,
  };
}
