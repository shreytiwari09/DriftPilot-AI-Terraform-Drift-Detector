// The state machine behind the pause control, as a plain reducer so it can be tested without a
// browser. The token is NOT in this state: it lives in a ref inside the component, because this
// state is rendered, compared and could be serialised.
import type { WorkflowState } from './githubControl';

export type ControlAction = 'pause' | 'resume' | 'scan';

export interface Note {
  kind: 'ok' | 'error';
  text: string;
}

export interface ControlState {
  connected: boolean;
  connecting: boolean;
  workflow: WorkflowState;
  busy: ControlAction | null;
  confirm: 'pause' | 'resume' | null;
  note: Note | null;
}

export type ControlEvent =
  | { type: 'connect' }
  | { type: 'connected'; workflow: WorkflowState }
  | { type: 'ask'; action: 'pause' | 'resume' }
  | { type: 'cancel' }
  | { type: 'start'; action: ControlAction }
  | { type: 'done'; workflow: WorkflowState; text: string }
  | { type: 'failed'; message: string; fatal: boolean }
  | { type: 'disconnect' };

export const initialState: ControlState = { connected: false, connecting: false, workflow: 'unknown', busy: null, confirm: null, note: null };

export function reduce(s: ControlState, e: ControlEvent): ControlState {
  switch (e.type) {
    case 'connect':
      return { ...initialState, connecting: true };
    case 'connected':
      return { ...initialState, connected: true, workflow: e.workflow };
    case 'ask':
      return { ...s, confirm: e.action, note: null };
    case 'cancel':
      return { ...s, confirm: null };
    case 'start':
      return { ...s, busy: e.action, confirm: null, note: null };
    case 'done':
      return { ...s, busy: null, workflow: e.workflow, note: { kind: 'ok', text: e.text } };
    case 'failed':
      // A rejected token ends the session: the page forgets it and asks for a new one.
      if (e.fatal) return { ...initialState, note: { kind: 'error', text: e.message } };
      return { ...s, connecting: false, busy: null, confirm: null, note: { kind: 'error', text: e.message } };
    case 'disconnect':
      return initialState;
  }
}

export type View = 'disconnected' | 'connecting' | 'active' | 'disabled' | 'unknown' | 'busy' | 'error';

export function view(s: ControlState): View {
  if (s.connecting) return 'connecting';
  if (s.busy) return 'busy';
  if (s.note?.kind === 'error') return 'error';
  if (!s.connected) return 'disconnected';
  return s.workflow;
}

export const stateLine = (w: WorkflowState): string =>
  w === 'active' ? 'Scans are running on schedule' : w === 'disabled' ? 'Scans are paused' : 'Could not tell whether scans are running';

/** What the confirmation dialog says will happen. The lamp turns amber after 3 x the cadence. */
export function consequence(action: 'pause' | 'resume', cadenceHours: number): string {
  return action === 'pause'
    ? `The dashboard will stop updating and the status lamp turns amber after ${3 * cadenceHours} h`
    : 'Scans resume on the next schedule';
}
