import type { BlindAttempt, BlindStep } from './api';

/** A Blind attempt as the API returns it, for tests. */
export function attemptFixture(overrides: Partial<BlindAttempt> = {}): BlindAttempt {
  return {
    id: 'attempt-1',
    session_id: 'session-1',
    status: 'active',
    void_reason: null,
    started_at: '2026-10-03T10:00:00Z',
    finished_at: null,
    passage_start_ms: 130_000,
    passage_end_ms: 280_000,
    position_ms: 130_000,
    resume_count: 0,
    resume_stop_ms: null,
    listen_complete: false,
    gist_text: null,
    ...overrides,
  };
}

/** The Blind step of a session, open and not yet tried unless an attempt is given. */
export function blindStepFixture(
  attempt: BlindAttempt | null = null,
  sessionId = 'session-1',
): BlindStep {
  return {
    session_id: sessionId,
    passage_start_ms: 130_000,
    passage_end_ms: 280_000,
    step_status: 'open',
    attempt,
  };
}
