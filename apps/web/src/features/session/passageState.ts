/**
 * The state of the passage choice: whole clip or a part, and the part's handles and typed
 * times. Until the learner moves a handle or types a time, the part follows the suggested
 * default, so it can move to the first speech once the peaks arrive.
 */
import { applyTyped, wholeFits, type Handle, type Range } from './passage';
import { formatClock } from './time';

export type PassageMode = 'whole' | 'part';

export interface PassageState {
  mode: PassageMode;
  /** The learner's own part; null while it is still the suggested default. */
  custom: Range | null;
  /** Typed text not applied yet (applied on blur, Enter or submit). */
  drafts: Partial<Record<Handle, string>>;
  errors: Partial<Record<Handle, string>>;
  /** How the last typed time was adjusted, shown under its field. */
  note: { handle: Handle; text: string } | null;
}

export type PassageAction =
  | { type: 'mode'; mode: PassageMode }
  | { type: 'set'; range: Range }
  | { type: 'replace'; state: PassageState }
  | { type: 'type'; handle: Handle; text: string }
  | { type: 'commit'; handle: Handle; base: Range; durationMs: number };

export function initialPassage(durationMs: number): PassageState {
  return {
    mode: wholeFits(durationMs) ? 'whole' : 'part',
    custom: null,
    drafts: {},
    errors: {},
    note: null,
  };
}

export function rangeOf(state: PassageState, base: Range): Range {
  return state.custom ?? base;
}

/** What a time field shows: the learner's draft, else the handle's position. */
export function textOf(state: PassageState, base: Range, handle: Handle): string {
  const range = rangeOf(state, base);
  return state.drafts[handle] ?? formatClock(handle === 'start' ? range.startMs : range.endMs);
}

/** The passage to send: the whole clip, or the part. */
export function selectedRange(state: PassageState, base: Range, durationMs: number): Range {
  return state.mode === 'whole' ? { startMs: 0, endMs: durationMs } : rangeOf(state, base);
}

export function passageReducer(state: PassageState, action: PassageAction): PassageState {
  switch (action.type) {
    case 'mode':
      return { ...state, mode: action.mode };
    case 'replace':
      return action.state;
    case 'set':
      // Handles are the source of truth: the fields follow them.
      return { ...state, custom: action.range, drafts: {}, errors: {}, note: null };
    case 'type': {
      const errors = { ...state.errors };
      delete errors[action.handle];
      const note = state.note?.handle === action.handle ? null : state.note;
      return { ...state, drafts: { ...state.drafts, [action.handle]: action.text }, errors, note };
    }
    case 'commit': {
      const { handle, base, durationMs } = action;
      const text = state.drafts[handle];
      if (text === undefined) return state;
      const drafts = { ...state.drafts };
      delete drafts[handle];
      const range = rangeOf(state, base);
      // Text that still shows the handle's position changes nothing (positions keep their ms).
      if (text.trim() === formatClock(handle === 'start' ? range.startMs : range.endMs)) {
        return { ...state, drafts };
      }
      const result = applyTyped(range, handle, text, durationMs);
      if (result.error) {
        return {
          ...state,
          errors: { ...state.errors, [handle]: result.error },
          note: state.note?.handle === handle ? null : state.note,
        };
      }
      const note = result.note
        ? { handle, text: result.note }
        : state.note?.handle === handle
          ? null
          : state.note;
      return { ...state, custom: result.range, drafts, note };
    }
  }
}

/**
 * Applies every pending draft, as on submit. `stop` names the field to send the learner to
 * when a time could not be read or was adjusted, so they see what changed before starting.
 */
export function commitAll(
  state: PassageState,
  base: Range,
  durationMs: number,
): { state: PassageState; stop: Handle | null } {
  if (state.mode === 'whole') return { state, stop: null };
  let next = state;
  let stop: Handle | null = null;
  for (const handle of ['start', 'end'] as const) {
    if (next.drafts[handle] === undefined) continue;
    const before = next;
    next = passageReducer(next, { type: 'commit', handle, base, durationMs });
    const adjusted = next.note !== before.note && next.note?.handle === handle;
    if (stop === null && (next.errors[handle] || adjusted)) stop = handle;
  }
  if (stop === null) {
    stop = next.errors.start ? 'start' : next.errors.end ? 'end' : null;
  }
  return { state: next, stop };
}
