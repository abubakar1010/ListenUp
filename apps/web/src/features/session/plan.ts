import type { components } from '../../api/schema';

export type Entry = components['schemas']['Entry'];
export type Step = components['schemas']['Step'];

export const STEP_NAMES: Record<Step, string> = {
  blind: 'Blind',
  dictation: 'Dictation',
  transcript: 'Transcript',
  card: 'Card',
  shadow: 'Shadow',
};

/** Each mode's one-line description on the entry choice (UI-2). */
export const STEP_DESCRIPTIONS: Record<Step, string> = {
  blind:
    'Listen once to the whole passage. No pausing, no rewinding. Then write a three-sentence gist.',
  dictation: 'Type every word you hear. Replay as often as you like. The text stays hidden.',
  transcript: "Read along and mark every place where the sound didn't match the words.",
  card: 'Keep up to 2 sounds you missed, to review later.',
  shadow: 'Speak with the speaker on a 60 to 90 s part: three recorded rounds.',
};

/** Each mode's rule in one line, shown above the work area (UI-2). */
export const STEP_RULES: Record<Step, string> = {
  blind: 'Listen once. No pausing, no rewinding.',
  dictation: 'Replay freely. The text stays hidden.',
  transcript: "Mark every place where the sound didn't match the words.",
  card: 'Keep up to 2 sounds you missed.',
  shadow: 'Three recorded rounds, speaking with the speaker.',
};

const FOLLOWING: Step[] = ['transcript', 'card', 'shadow'];

/** The plan's steps in order (FR-PL-2): Blind comes first when both are chosen (OQ-1). */
export function pathFor(entry: Entry): Step[] {
  if (entry === 'both') return ['blind', 'dictation', ...FOLLOWING];
  return [entry, ...FOLLOWING];
}

/** The entry for two ticked boxes, or null when neither is ticked. */
export function entryFrom(blind: boolean, dictation: boolean): Entry | null {
  if (blind && dictation) return 'both';
  if (blind) return 'blind';
  if (dictation) return 'dictation';
  return null;
}

export function entryIncludes(entry: Entry, step: 'blind' | 'dictation'): boolean {
  return entry === 'both' || entry === step;
}
