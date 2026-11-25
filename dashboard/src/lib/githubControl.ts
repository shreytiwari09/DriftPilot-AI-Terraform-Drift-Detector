// Pause, resume and start the repository's DriftPilot workflow through GitHub's REST API.
//
// This is the only code in the app that sends a token anywhere, and it sends it to one place:
// https://api.github.com, in an Authorization header. The token is a parameter of each call. It is
// never put in a URL, a log line, an error message, storage or any value the app keeps.
// Every failure is turned into a plain sentence here, so callers never see a raw error.
import type { Links } from '../types';

const API = 'https://api.github.com';
const REPO = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;
const WORKFLOW = /^[A-Za-z0-9_.-]+\.ya?ml$/;
const BRANCH = /^[A-Za-z0-9_][A-Za-z0-9_./-]{0,99}$/;
const TOKEN_SHAPE = /^[\x21-\x7e]{8,255}$/; // printable ASCII, no spaces: also rules out header tricks
const INVISIBLE = new RegExp('[\\u0000-\\u001f\\u007f-\\u009f\\u200b-\\u200f\\u2028\\u2029\\u202a-\\u202e\\u2060-\\u2069\\ufeff]', 'g');

export interface ControlTarget {
  owner: string;
  repo: string;
  workflow: string;
  branch: string;
}

export type WorkflowState = 'active' | 'disabled' | 'unknown';

/** An error whose message is always safe to show: a fixed sentence, plus a cleaned GitHub message at most. */
export class ControlError extends Error {
  readonly status: number | null;
  constructor(message: string, status: number | null = null) {
    super(message);
    this.name = 'ControlError';
    this.status = status;
  }
}

const plain = (s: string) => !s.includes('..');

/** The repository, workflow and branch the control may touch, or null (then the control stays hidden). */
export function controlTarget(links: Links | null | undefined): ControlTarget | null {
  const { repo, workflow, branch } = links ?? {};
  if (typeof repo !== 'string' || typeof workflow !== 'string' || typeof branch !== 'string') return null;
  if (!REPO.test(repo) || !WORKFLOW.test(workflow) || !BRANCH.test(branch)) return null;
  const [owner, name] = repo.split('/');
  if ([owner, name].some((p) => p === '.' || p === '..') || !plain(repo) || !plain(workflow)) return null;
  if (!plain(branch) || branch.includes('//') || /[/.]$/.test(branch) || branch.endsWith('.lock')) return null;
  return { owner, repo: name, workflow, branch };
}

/** The workflow's API address. It takes the target only: there is no way to pass a token into it. */
export function workflowUrl(t: ControlTarget, suffix: '' | '/disable' | '/enable' | '/dispatches' = ''): string {
  const e = encodeURIComponent;
  return `${API}/repos/${e(t.owner)}/${e(t.repo)}/actions/workflows/${e(t.workflow)}${suffix}`;
}

/** Text from GitHub that is safe to show: no control or invisible characters, no token, at most 200 characters. */
export function sanitizeMessage(raw: unknown, token: string): string {
  if (typeof raw !== 'string') return '';
  const drop = (s: string) => (token ? s.split(token).join('[removed]') : s);
  const text = drop(drop(raw).replace(/\s+/g, ' ').replace(INVISIBLE, '')); // twice: invisible characters may have split it
  return text.trim().slice(0, 200);
}

const HEADERS = (token: string): Record<string, string> => ({
  Authorization: `Bearer ${token}`,
  Accept: 'application/vnd.github+json',
  'X-GitHub-Api-Version': '2022-11-28',
});

async function messageOf(res: Response, token: string): Promise<string> {
  try {
    const body: unknown = await res.json();
    return sanitizeMessage((body as { message?: unknown } | null)?.message, token);
  } catch {
    return '';
  }
}

/** Turns a refused response into a ControlError with a plain sentence. */
async function refusal(res: Response, token: string): Promise<ControlError> {
  const status = res.status;
  if (res.type === 'opaqueredirect' || (status >= 300 && status < 400)) {
    return new ControlError('GitHub redirected the request. The repository may have been renamed or moved: check dashboard.links.repo', status);
  }
  if (status === 401) return new ControlError('GitHub rejected the token', status);
  const message = await messageOf(res, token);
  if (status === 429 || (status === 403 && (res.headers.get('x-ratelimit-remaining') === '0' || /rate limit/i.test(message)))) {
    return new ControlError('GitHub rate limit reached. Wait a few minutes and try again', status);
  }
  if (status === 403) return new ControlError('The token cannot change Actions on this repository (needs Actions: read and write)', status);
  if (status === 404) return new ControlError('Workflow or repository not found, or the token cannot see it', status);
  return new ControlError(`GitHub refused the request (${status})${message ? `: ${message}` : ''}`, status);
}

async function call(t: ControlTarget, rawToken: string, method: 'GET' | 'PUT' | 'POST', suffix: '' | '/disable' | '/enable' | '/dispatches', expect: number): Promise<Response> {
  const token = typeof rawToken === 'string' ? rawToken.trim() : '';
  if (!TOKEN_SHAPE.test(token)) throw new ControlError('That does not look like a GitHub token');
  const headers = HEADERS(token);
  const init: RequestInit = { method, headers, cache: 'no-store', credentials: 'omit', redirect: 'manual', referrerPolicy: 'no-referrer' };
  if (suffix === '/dispatches') {
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify({ ref: t.branch });
  }
  let res: Response;
  try {
    res = await fetch(workflowUrl(t, suffix), init);
  } catch {
    throw new ControlError('Could not reach GitHub'); // the browser's own message is dropped on purpose
  }
  if (res.status === expect) return res;
  if (res.ok) throw new ControlError(`GitHub answered unexpectedly (status ${res.status})`, res.status);
  throw await refusal(res, token);
}

/** The four calls for one workflow. Each takes the token as an argument and keeps nothing. */
export function githubControl(target: ControlTarget) {
  return {
    /** Reads whether the workflow is enabled. */
    async getState(token: string): Promise<WorkflowState> {
      const res = await call(target, token, 'GET', '', 200);
      try {
        const body = (await res.json()) as { state?: unknown };
        if (body.state === 'active') return 'active';
        if (body.state === 'disabled_manually' || body.state === 'disabled_inactivity' || body.state === 'disabled_fork') return 'disabled';
      } catch {
        /* an unreadable answer is "unknown", not an error */
      }
      return 'unknown';
    },
    async pause(token: string): Promise<void> {
      await call(target, token, 'PUT', '/disable', 204);
    },
    async resume(token: string): Promise<void> {
      await call(target, token, 'PUT', '/enable', 204);
    },
    /** Starts one run on the configured branch (the workflow needs a workflow_dispatch trigger). */
    async scanNow(token: string): Promise<void> {
      await call(target, token, 'POST', '/dispatches', 204);
    },
  };
}
