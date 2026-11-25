import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ControlError, controlTarget, githubControl, sanitizeMessage, workflowUrl, type ControlTarget } from '../src/lib/githubControl';
import { consequence, initialState, reduce, stateLine, view, type ControlEvent, type ControlState } from '../src/lib/controlState';

const TOKEN = 'github_pat_11ABCDEF0_SECRETSECRETSECRETSECRETSECRET';
const TARGET: ControlTarget = { owner: 'acme', repo: 'infra', workflow: 'driftpilot.yml', branch: 'main' };
const BASE = 'https://api.github.com/repos/acme/infra/actions/workflows/driftpilot.yml';

type Call = { url: string; init: RequestInit };
let calls: Call[];

/** A fetch that answers from a queue and records what it was asked. No real network. */
function mockFetch(...answers: (Response | Error)[]) {
  calls = [];
  const queue = [...answers];
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit) => {
    calls.push({ url: String(url), init });
    const next = queue.shift() ?? new Response(null, { status: 204 });
    if (next instanceof Error) throw next;
    return next;
  }));
}
const json = (body: unknown, status = 200, headers: Record<string, string> = {}) => new Response(JSON.stringify(body), { status, headers });
const empty = (status = 204) => new Response(null, { status });
const header = (c: Call, name: string) => (c.init.headers as Record<string, string>)[name];
const errorOf = async (p: Promise<unknown>): Promise<ControlError> => {
  try { await p; } catch (e) { return e as ControlError; }
  throw new Error('expected a rejection');
};

beforeEach(() => mockFetch());
afterEach(() => vi.unstubAllGlobals());

describe('controlTarget', () => {
  const ok = { repo: 'acme/infra', workflow: 'driftpilot.yml', branch: 'main' };
  it('accepts a normal repo, workflow and branch', () => {
    expect(controlTarget(ok)).toEqual(TARGET);
    expect(controlTarget({ ...ok, workflow: 'Drift_Pilot-2.yaml', branch: 'release/2.2' })).toMatchObject({ workflow: 'Drift_Pilot-2.yaml', branch: 'release/2.2' });
  });
  it('hides the control for anything missing or odd', () => {
    expect(controlTarget(undefined)).toBeNull();
    expect(controlTarget(null)).toBeNull();
    expect(controlTarget({ ...ok, repo: null })).toBeNull();
    for (const repo of ['acme', 'a/b/c', 'acme/in fra', 'acme/infra?x=1', 'acme/infra#h', '../infra', 'acme/..', './x', 'acme\\infra', 'ac me/x', 'acme/infra\n', 'https://github.com/acme/infra']) {
      expect(controlTarget({ ...ok, repo }), repo).toBeNull();
    }
    for (const workflow of ['driftpilot', 'driftpilot.yml/disable', '../x.yml', 'a b.yml', 'x.yml?y', 'x.json', 'a..b.yml', '.yml']) {
      expect(controlTarget({ ...ok, workflow }), workflow).toBeNull();
    }
    for (const branch of ['', '-main', '/main', 'a..b', 'a b', 'main?x', 'main#x', 'a//b', 'main/', 'main.', 'x.lock', 'a\nb', 'x'.repeat(101), 'refs/heads/main;rm']) {
      expect(controlTarget({ ...ok, branch }), branch).toBeNull();
    }
  });
});

describe('workflowUrl', () => {
  it('builds the workflow address from the target only, with every part encoded', () => {
    expect(workflowUrl(TARGET)).toBe(BASE);
    expect(workflowUrl(TARGET, '/disable')).toBe(`${BASE}/disable`);
    expect(workflowUrl.length).toBeLessThanOrEqual(2); // (target, suffix): there is no place to pass a token
  });
});

describe('the four calls', () => {
  it('getState: GET, the three headers, no body', async () => {
    mockFetch(json({ state: 'active' }));
    await githubControl(TARGET).getState(TOKEN);
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe(BASE);
    expect(calls[0].init.method).toBe('GET');
    expect(header(calls[0], 'Authorization')).toBe(`Bearer ${TOKEN}`);
    expect(header(calls[0], 'Accept')).toBe('application/vnd.github+json');
    expect(header(calls[0], 'X-GitHub-Api-Version')).toBe('2022-11-28');
    expect(calls[0].init.body).toBeUndefined();
    expect(calls[0].init.credentials).toBe('omit');
    expect(calls[0].init.referrerPolicy).toBe('no-referrer');
  });
  it('pause: PUT .../disable, resume: PUT .../enable', async () => {
    await githubControl(TARGET).pause(TOKEN);
    await githubControl(TARGET).resume(TOKEN);
    expect(calls.map((c) => [c.init.method, c.url])).toEqual([['PUT', `${BASE}/disable`], ['PUT', `${BASE}/enable`]]);
    for (const c of calls) {
      expect(header(c, 'Authorization')).toBe(`Bearer ${TOKEN}`);
      expect(header(c, 'X-GitHub-Api-Version')).toBe('2022-11-28');
      expect(c.init.body).toBeUndefined();
    }
  });
  it('scanNow: POST .../dispatches with {ref: branch}', async () => {
    await githubControl({ ...TARGET, branch: 'release/2.2' }).scanNow(TOKEN);
    expect(calls[0].url).toBe(`${BASE}/dispatches`);
    expect(calls[0].init.method).toBe('POST');
    expect(JSON.parse(String(calls[0].init.body))).toEqual({ ref: 'release/2.2' });
    expect(header(calls[0], 'Content-Type')).toBe('application/json');
  });
  it('only ever talks to api.github.com, and the token is in no URL', async () => {
    mockFetch(json({ state: 'active' }));
    const api = githubControl(TARGET);
    await api.getState(TOKEN);
    await api.pause(TOKEN);
    await api.resume(TOKEN);
    await api.scanNow(TOKEN);
    expect(calls).toHaveLength(4);
    for (const c of calls) {
      expect(c.url.startsWith('https://api.github.com/repos/acme/infra/actions/workflows/driftpilot.yml')).toBe(true);
      expect(c.url).not.toContain(TOKEN);
      expect(c.url).not.toContain('?');
      expect(String(c.init.body ?? '')).not.toContain(TOKEN);
    }
  });
  it('expects exactly 204 for the three writes', async () => {
    mockFetch(empty(200), empty(202), empty(200));
    for (const call of [() => githubControl(TARGET).pause(TOKEN), () => githubControl(TARGET).resume(TOKEN), () => githubControl(TARGET).scanNow(TOKEN)]) {
      const e = await errorOf(call());
      expect(e).toBeInstanceOf(ControlError);
      expect(e.message).toContain('unexpected');
    }
  });
});

describe('state mapping', () => {
  it.each([
    ['active', 'active'], ['disabled_manually', 'disabled'], ['disabled_inactivity', 'disabled'], ['disabled_fork', 'disabled'],
    ['deleted', 'unknown'], ['something_new', 'unknown'],
  ])('%s -> %s', async (raw, mapped) => {
    mockFetch(json({ state: raw }));
    expect(await githubControl(TARGET).getState(TOKEN)).toBe(mapped);
  });
  it('is unknown when the answer is not what was expected', async () => {
    mockFetch(json({ nope: 1 }));
    expect(await githubControl(TARGET).getState(TOKEN)).toBe('unknown');
    mockFetch(new Response('not json', { status: 200 }));
    expect(await githubControl(TARGET).getState(TOKEN)).toBe('unknown');
  });
});

describe('errors say what happened in plain words', () => {
  it.each([
    [401, 'GitHub rejected the token'],
    [403, 'The token cannot change Actions on this repository (needs Actions: read and write)'],
    [404, 'Workflow or repository not found, or the token cannot see it'],
  ])('%i', async (status, text) => {
    mockFetch(json({ message: 'Bad credentials', documentation_url: 'https://docs.github.com' }, status));
    const e = await errorOf(githubControl(TARGET).pause(TOKEN));
    expect(e.message).toBe(text);
    expect(e.status).toBe(status);
  });
  it('403 and 429 with an exhausted limit say so', async () => {
    mockFetch(json({ message: 'API rate limit exceeded for user' }, 403, { 'x-ratelimit-remaining': '0' }), json({ message: 'slow down' }, 429));
    expect((await errorOf(githubControl(TARGET).getState(TOKEN))).message).toMatch(/rate limit/i);
    expect((await errorOf(githubControl(TARGET).getState(TOKEN))).message).toMatch(/rate limit/i);
  });
  it('other statuses carry a short cleaned GitHub message', async () => {
    mockFetch(json({ message: "Workflow does not have 'workflow_dispatch' trigger" }, 422));
    const e = await errorOf(githubControl(TARGET).scanNow(TOKEN));
    expect(e.message).toBe("GitHub refused the request (422): Workflow does not have 'workflow_dispatch' trigger");
  });
  it('a body that is not JSON adds nothing', async () => {
    mockFetch(new Response('<html>oops</html>', { status: 500 }));
    expect((await errorOf(githubControl(TARGET).getState(TOKEN))).message).toBe('GitHub refused the request (500)');
  });
  it('a redirect (renamed repository) is reported, not followed', async () => {
    mockFetch(new Response(null, { status: 301, headers: { location: 'https://api.github.com/repositories/1/actions' } }));
    const e = await errorOf(githubControl(TARGET).getState(TOKEN));
    expect(e.message).toMatch(/renamed|moved/);
    expect(calls[0].init.redirect).toBe('manual');
  });
  it('a network failure is "Could not reach GitHub", whatever the browser said', async () => {
    mockFetch(new TypeError(`Failed to fetch ${TOKEN}`));
    const e = await errorOf(githubControl(TARGET).getState(TOKEN));
    expect(e.message).toBe('Could not reach GitHub');
    expect(e.status).toBeNull();
    expect(JSON.stringify(e) + e.message + String(e.stack)).not.toContain(TOKEN.slice(10));
  });
  it('the token never appears in any error message, even if GitHub echoes it back', async () => {
    mockFetch(json({ message: `Bad token ${TOKEN} given` }, 422), json({ message: TOKEN }, 400));
    for (let i = 0; i < 2; i++) {
      const e = await errorOf(githubControl(TARGET).pause(TOKEN));
      expect(e.message).not.toContain(TOKEN);
      expect(e.message).not.toContain('SECRETSECRET');
    }
  });
  it('refuses a token that is not a plausible token before any request', async () => {
    for (const bad of ['', '   ', 'short', 'has space inside token', 'line\nbreak_token_value', 'unicode-\u00e9-token-value', 'x'.repeat(300)]) {
      const e = await errorOf(githubControl(TARGET).getState(bad));
      expect(e).toBeInstanceOf(ControlError);
      expect(e.message).toBe('That does not look like a GitHub token');
      expect(e.message).not.toContain(bad || 'zzz');
    }
    expect(calls).toHaveLength(0);
  });
  it('trims the whitespace a paste often brings', async () => {
    mockFetch(json({ state: 'active' }));
    await githubControl(TARGET).getState(`  ${TOKEN}\n`);
    expect(header(calls[0], 'Authorization')).toBe(`Bearer ${TOKEN}`);
  });
});

describe('sanitizeMessage', () => {
  it('strips control and invisible characters, collapses spaces and caps at 200 characters', () => {
    expect(sanitizeMessage('a\u0000b\u001b[31mc\u202Ed\u200Be\u0085  f\n\tg', TOKEN)).toBe('ab[31mcde f g');
    const long = sanitizeMessage('x'.repeat(500), TOKEN);
    expect(long.length).toBe(200);
  });
  it('removes the token, also when it was split by invisible characters or when only part would remain', () => {
    expect(sanitizeMessage(`before ${TOKEN} after`, TOKEN)).toBe('before [removed] after');
    const split = `${TOKEN.slice(0, 20)}\u200B${TOKEN.slice(20)}`;
    expect(sanitizeMessage(split, TOKEN)).not.toContain(TOKEN.slice(20));
    const edge = `${'y'.repeat(195)}${TOKEN}`;
    expect(sanitizeMessage(edge, TOKEN)).not.toContain(TOKEN.slice(0, 8));
  });
  it('is empty for anything that is not text', () => {
    expect(sanitizeMessage(undefined, TOKEN)).toBe('');
    expect(sanitizeMessage({ a: 1 }, TOKEN)).toBe('');
  });
});

describe('the state machine (no component runtime here, so the reducer carries the logic)', () => {
  const run = (...events: ControlEvent[]): ControlState => events.reduce(reduce, initialState);
  it('starts disconnected and has no place for a token', () => {
    expect(view(initialState)).toBe('disconnected');
    expect(JSON.stringify(initialState)).not.toMatch(/token/i);
  });
  it('connecting, then active or disabled', () => {
    expect(view(run({ type: 'connect' }))).toBe('connecting');
    expect(view(run({ type: 'connect' }, { type: 'connected', workflow: 'active' }))).toBe('active');
    expect(view(run({ type: 'connect' }, { type: 'connected', workflow: 'disabled' }))).toBe('disabled');
    expect(view(run({ type: 'connect' }, { type: 'connected', workflow: 'unknown' }))).toBe('unknown');
  });
  it('a failed connect goes back to disconnected with the error shown', () => {
    const s = run({ type: 'connect' }, { type: 'failed', message: 'GitHub rejected the token', fatal: true });
    expect(s.connected).toBe(false);
    expect(view(s)).toBe('error');
    expect(s.note).toEqual({ kind: 'error', text: 'GitHub rejected the token' });
  });
  it('pause and resume ask first, cancel changes nothing', () => {
    const on = run({ type: 'connect' }, { type: 'connected', workflow: 'active' });
    expect(reduce(on, { type: 'ask', action: 'pause' }).confirm).toBe('pause');
    expect(reduce(reduce(on, { type: 'ask', action: 'pause' }), { type: 'cancel' })).toEqual(on);
  });
  it('a running action is busy, then done with a note and the re-read state', () => {
    const on = run({ type: 'connect' }, { type: 'connected', workflow: 'active' }, { type: 'ask', action: 'pause' });
    const busy = reduce(on, { type: 'start', action: 'pause' });
    expect(view(busy)).toBe('busy');
    expect(busy.confirm).toBeNull();
    const done = reduce(busy, { type: 'done', workflow: 'disabled', text: 'Scans are paused.' });
    expect(view(done)).toBe('disabled');
    expect(done.busy).toBeNull();
    expect(done.note).toEqual({ kind: 'ok', text: 'Scans are paused.' });
  });
  it('a failed action keeps the connection and shows the error', () => {
    const busy = run({ type: 'connect' }, { type: 'connected', workflow: 'active' }, { type: 'start', action: 'scan' });
    const s = reduce(busy, { type: 'failed', message: 'GitHub rejected the token', fatal: false });
    expect(s.connected).toBe(true);
    expect(view(s)).toBe('error');
    expect(s.busy).toBeNull();
  });
  it('a fatal error (token rejected) disconnects', () => {
    const busy = run({ type: 'connect' }, { type: 'connected', workflow: 'active' }, { type: 'start', action: 'pause' });
    const s = reduce(busy, { type: 'failed', message: 'GitHub rejected the token', fatal: true });
    expect(s.connected).toBe(false);
    expect(s.workflow).toBe('unknown');
  });
  it('disconnect clears everything', () => {
    const s = run({ type: 'connect' }, { type: 'connected', workflow: 'disabled' }, { type: 'disconnect' });
    expect(s).toEqual(initialState);
  });
  it('the words: state line and consequences scale with the cadence', () => {
    expect(stateLine('active')).toBe('Scans are running on schedule');
    expect(stateLine('disabled')).toBe('Scans are paused');
    expect(consequence('pause', 12)).toBe('The dashboard will stop updating and the status lamp turns amber after 36 h');
    expect(consequence('pause', 6)).toContain('after 18 h');
    expect(consequence('resume', 12)).toBe('Scans resume on the next schedule');
  });
});

describe('the source keeps the token in memory only', () => {
  const SRC = join(__dirname, '../src');
  const files = (dir: string): string[] => readdirSync(dir).flatMap((n) => (statSync(join(dir, n)).isDirectory() ? files(join(dir, n)) : /\.tsx?$/.test(n) ? [join(dir, n)] : []));
  const text = (p: string) => readFileSync(p, 'utf8');
  const CONTROL = ['lib/githubControl.ts', 'lib/controlState.ts', 'components/PauseControl.tsx', 'pages/Scans.tsx'].map((f) => join(SRC, f));

  it('the control files use no storage API, no cookie, no console, no URL fragment', () => {
    for (const f of CONTROL) {
      const t = text(f);
      expect(t, f).not.toMatch(/localStorage|sessionStorage|indexedDB|document\.cookie|caches\.|console\.|location\.hash|history\.(push|replace)State|BroadcastChannel|postMessage|navigator\.sendBeacon|XMLHttpRequest|WebSocket|window\.name/);
    }
  });
  it('the only storage use in all of src is the theme choice', () => {
    const users = files(SRC).filter((f) => /localStorage|sessionStorage|document\.cookie/.test(text(f))).map((f) => f.slice(SRC.length + 1));
    expect(users).toEqual(['lib/theme.tsx']);
  });
  it('fetch is called only by the data loader and the control, and the control only names api.github.com', () => {
    const users = files(SRC).filter((f) => /\bfetch\(/.test(text(f))).map((f) => f.slice(SRC.length + 1)).sort();
    expect(users).toEqual(['lib/githubControl.ts', 'lib/useData.ts']);
    const code = text(join(SRC, 'lib/githubControl.ts')).replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
    const urls = code.match(/https?:\/\/[^\s'"`)]+/g) ?? [];
    expect(urls).toEqual(['https://api.github.com']);
  });
  it('the token reaches no template string except the Authorization header', () => {
    for (const f of CONTROL) {
      for (const line of text(f).split('\n')) {
        if (/\$\{\s*token\b/.test(line)) expect(line, f).toMatch(/Bearer \$\{token\}/);
      }
    }
  });
  it('the token field has no name, no autofill, and no value attribute', () => {
    const t = text(join(SRC, 'components/PauseControl.tsx'));
    expect(t).toMatch(/type="password"/);
    expect(t).toMatch(/autoComplete="off"/);
    expect(t).toMatch(/spellCheck=\{false\}/);
    const input = t.match(/<input[\s\S]*?\/>/)?.[0] ?? '';
    expect(input).not.toMatch(/\bname=|\bvalue=|defaultValue=/);
  });
  it('the page carries a connect-src policy that allows only itself and api.github.com', () => {
    const html = text(join(__dirname, '../index.html'));
    const meta = html.match(/<meta http-equiv="Content-Security-Policy" content="([^"]*)"/)?.[1];
    expect(meta).toBe("connect-src 'self' https://api.github.com");
  });
});
