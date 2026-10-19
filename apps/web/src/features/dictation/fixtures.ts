import type { DictationResult } from './api';

// The AT-3 fixture: "street" typed as "streat", "to" left out, "quickly" added.
export const RESULT: DictationResult = {
  accuracy: 90,
  counts: { correct: 8, spelling_slip: 1, wrong: 0, missing: 1, extra: 1 },
  items: [
    { index: 0, status: 'correct', word: 'Cities', typed: 'Cities' },
    { index: 2, status: 'spelling_slip', word: 'street', typed: 'streat' },
    { index: 4, status: 'missing', word: 'to', typed: '' },
    { index: 5, status: 'wrong', word: 'cool', typed: 'cold' },
    { index: null, status: 'extra', word: '', typed: 'quickly' },
    { index: 9, status: 'correct', word: 'summer.', typed: 'summer' },
  ],
};
