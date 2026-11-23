import type { components } from '../../api/schema';

type Scored = components['schemas']['RoundFeedbackScored'];

/** A released, non-synthetic round grade as the API would return it, for tests. */
export const SCORED_ROUND: Scored = {
  status: 'scored',
  overall: 75,
  measures: {
    timing: { score: 80, reason: null },
    pronunciation: { score: 70, reason: null },
    articulation: { score: 60, reason: null },
    fluency: { score: 90, reason: null },
    fillers: { score: 100, reason: null },
    completeness: { score: null, reason: 'no_matched_words' },
  },
  accent: {
    score: 42,
    reason: null,
    experimental: true,
    compared_with: 'this_speaker',
    in_overall: false,
  },
  word_labels: [
    { index: 0, text: 'Hello', label: 'good', score: 90, reasons: [] },
    {
      index: 1,
      text: 'world.',
      label: 'needs_work',
      score: 55,
      reasons: [{ sound: 'd', position: 'final', issue: 'dropped', linking: true }],
    },
    { index: 2, text: 'Again.', label: 'missed', score: null, reasons: [] },
  ],
};

/** A recorded round as `GET /sessions/{id}/shadow/rounds` lists it, for tests. */
export function roundFixture(
  round: number,
  overrides: Partial<components['schemas']['Round']> = {},
): components['schemas']['Round'] {
  return {
    id: `r${round}`,
    round,
    playback_status: 'ended',
    recorded_at: '2026-11-01T10:00:00Z',
    recording_available: true,
    transcript_shown: round === 1,
    feedback: 'unavailable',
    ...overrides,
  };
}
