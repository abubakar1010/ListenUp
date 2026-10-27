import type { MarkTag } from './markSync';

/** FR-TR-4: the four tags in words, in the order the learner chooses from. */
export const TAG_LABELS: Record<MarkTag, string> = {
  linking: 'Linking',
  reduction: 'Reduction',
  weak_form: 'Weak form',
  unknown_word: 'Unknown word',
};

export const TAGS = Object.keys(TAG_LABELS) as MarkTag[];
