import { useEffect, useId, useReducer, useRef, useState, type FormEvent } from 'react';
import { consequence, initialState, reduce, stateLine, type ControlAction } from '../lib/controlState';
import { ControlError, githubControl, type ControlTarget, type WorkflowState } from '../lib/githubControl';
import { Icon, StatusText } from './ui';

const DOT: Record<WorkflowState, string> = { active: 'bg-ok', disabled: 'bg-med', unknown: 'bg-low' };
const BUSY_LABEL: Record<ControlAction, string> = { pause: 'Pausing…', resume: 'Resuming…', scan: 'Starting…' };

/** Asks before a pause or a resume. A native modal dialog: focus stays inside, Escape closes it. */
function Confirm({ action, cadence, onYes, onNo }: { action: 'pause' | 'resume'; cadence: number; onYes: () => void; onNo: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const title = useId();
  const body = useId();
  useEffect(() => {
    const d = ref.current;
    if (d && !d.open) d.showModal();
  }, []);
  return (
    <dialog ref={ref} aria-labelledby={title} aria-describedby={body} onClose={onNo} onCancel={onNo} className="w-[min(92vw,420px)] rounded-2xl border border-line bg-surface p-5 text-ink shadow-pop backdrop:bg-black/50">
      <h3 id={title} className="h-card">{action === 'pause' ? 'Pause scans?' : 'Resume scans?'}</h3>
      <p id={body} className="mt-2 text-sm text-ink2">{consequence(action, cadence)}</p>
      <div className="mt-5 flex justify-end gap-2">
        <button type="button" className="btn btn-ghost" onClick={onNo}>Cancel</button>
        <button type="button" className="btn btn-primary" onClick={onYes}>{action === 'pause' ? 'Pause scans' : 'Resume scans'}</button>
      </div>
    </dialog>
  );
}

/**
 * Optional pause / resume / scan-now control. The token is held in a ref in this component only:
 * it is not in any state, store, storage, URL or DOM attribute, and it is dropped on Disconnect,
 * when this page is left (unmount) and on pagehide.
 */
export default function PauseControl({ target, cadence, onWorkflow }: { target: ControlTarget; cadence: number; onWorkflow: (w: WorkflowState | null) => void }) {
  const [open, setOpen] = useState(false);
  const [s, dispatch] = useReducer(reduce, initialState);
  const tokenRef = useRef<string | null>(null);
  const session = useRef(0); // bumped on every disconnect: answers that arrive later are ignored
  const inputRef = useRef<HTMLInputElement>(null);
  const lineRef = useRef<HTMLDivElement>(null);
  const openerRef = useRef<HTMLElement | null>(null); // the button that opened the dialog, to give focus back
  const panel = useId();
  const field = useId();
  const api = githubControl(target);

  useEffect(() => {
    const forget = () => {
      tokenRef.current = null;
      session.current += 1;
      dispatch({ type: 'disconnect' });
    };
    window.addEventListener('pagehide', forget);
    return () => {
      window.removeEventListener('pagehide', forget);
      tokenRef.current = null;
      session.current += 1;
    };
  }, []);

  useEffect(() => {
    onWorkflow(s.connected ? s.workflow : null);
  }, [s.connected, s.workflow, onWorkflow]);

  const disconnect = () => {
    tokenRef.current = null;
    session.current += 1;
    dispatch({ type: 'disconnect' });
  };
  const ask = (action: 'pause' | 'resume') => {
    openerRef.current = document.activeElement as HTMLElement | null;
    dispatch({ type: 'ask', action });
  };
  const cancel = () => {
    dispatch({ type: 'cancel' });
    window.setTimeout(() => openerRef.current?.focus(), 0);
  };
  const messageOf = (e: unknown) => (e instanceof ControlError ? e.message : 'Something went wrong');

  const connect = async (ev: FormEvent) => {
    ev.preventDefault();
    const input = inputRef.current;
    const token = input?.value ?? '';
    if (input) input.value = ''; // the field never keeps it, not even when the call fails
    const mine = session.current;
    dispatch({ type: 'connect' });
    try {
      const workflow = await api.getState(token);
      if (session.current !== mine) return;
      tokenRef.current = token.trim();
      dispatch({ type: 'connected', workflow });
    } catch (e) {
      if (session.current === mine) dispatch({ type: 'failed', message: messageOf(e), fatal: true });
    }
  };

  const run = async (action: ControlAction) => {
    const token = tokenRef.current;
    if (!token) return;
    const mine = session.current;
    dispatch({ type: 'start', action });
    try {
      if (action === 'pause') await api.pause(token);
      else if (action === 'resume') await api.resume(token);
      else await api.scanNow(token);
      const expected: WorkflowState = action === 'pause' ? 'disabled' : action === 'resume' ? 'active' : s.workflow;
      let workflow = expected;
      let reread = true;
      try {
        workflow = await api.getState(token);
      } catch {
        reread = false;
      }
      if (session.current !== mine) return;
      const said = action === 'pause' ? 'Scans are paused.' : action === 'resume' ? 'Scans are resumed. The next run follows the schedule.' : 'Scan requested. It usually appears under Actions within a few seconds.';
      dispatch({ type: 'done', workflow, text: reread ? said : `${said} Could not re-read the state from GitHub.` });
      lineRef.current?.focus();
    } catch (e) {
      if (session.current !== mine) return;
      const fatal = e instanceof ControlError && e.status === 401;
      if (fatal) tokenRef.current = null;
      dispatch({ type: 'failed', message: messageOf(e), fatal });
    }
  };

  const note = s.note ? <p className={s.note.kind === 'error' ? 'text-crit' : 'text-ink2'}>{s.note.text}</p> : null;

  return (
    <div className="mt-5 border-t border-line pt-3">
      <button type="button" className="inline-flex h-8 items-center gap-1.5 rounded-lg text-[13px] text-ink2 transition-colors hover:text-ink" aria-expanded={open} aria-controls={panel} onClick={() => setOpen(!open)}>
        <Icon name="chevron-down" className={`h-4 w-4 transition-transform ${open ? 'rotate-180' : ''}`} />
        Control from this page
      </button>
      <div id={panel} hidden={!open} className="mt-2 space-y-4">
        <p className="max-w-prose text-sm text-ink2">
          This page can pause or resume scans by calling GitHub with a token you paste. The token stays in this tab&apos;s memory only and is forgotten on reload or Disconnect. Use a token limited to this one repository with only the Actions permission, and a short expiry. Anyone with the token can pause your scans.
        </p>

        {!s.connected ? (
          <form onSubmit={(ev) => void connect(ev)} className="flex max-w-md flex-col gap-2">
            <label htmlFor={field} className="label !mb-0">GitHub token</label>
            <div className="flex gap-2">
              <input
                id={field}
                ref={inputRef}
                type="password"
                className="field"
                autoComplete="off"
                autoCapitalize="off"
                spellCheck={false}
                data-1p-ignore="true"
                data-lpignore="true"
                data-bwignore="true"
                data-form-type="other"
                disabled={s.connecting}
                placeholder="github_pat_…"
              />
              <button type="submit" className="btn" disabled={s.connecting}>{s.connecting ? 'Connecting…' : 'Connect'}</button>
            </div>
          </form>
        ) : (
          <div className="space-y-3">
            <div ref={lineRef} tabIndex={-1} className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg outline-none focus-visible:outline-2">
              <StatusText dot={DOT[s.workflow]}><span className="font-medium">{stateLine(s.workflow)}</span></StatusText>
              <span className="font-mono text-xs text-mute">{target.owner}/{target.repo} · {target.workflow}</span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {s.workflow !== 'disabled' && <button type="button" className="btn" disabled={!!s.busy} onClick={() => ask('pause')}>{s.busy === 'pause' ? BUSY_LABEL.pause : 'Pause scans'}</button>}
              {s.workflow === 'disabled' && <button type="button" className="btn" disabled={!!s.busy} onClick={() => ask('resume')}>{s.busy === 'resume' ? BUSY_LABEL.resume : 'Resume scans'}</button>}
              <button type="button" className="btn" disabled={!!s.busy || s.workflow === 'disabled'} title={s.workflow === 'disabled' ? 'Resume scans first: GitHub does not start a disabled workflow' : undefined} onClick={() => void run('scan')}>{s.busy === 'scan' ? BUSY_LABEL.scan : 'Run a scan now'}</button>
              <button type="button" className="btn btn-ghost" disabled={!!s.busy} onClick={disconnect}>Disconnect</button>
            </div>
          </div>
        )}
        <div aria-live="polite" className="min-h-5 text-sm">{note}</div>
      </div>
      {s.confirm && <Confirm action={s.confirm} cadence={cadence} onYes={() => void run(s.confirm as ControlAction)} onNo={cancel} />}
    </div>
  );
}
