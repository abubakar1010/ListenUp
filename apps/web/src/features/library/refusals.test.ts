import { ApiError, type Problem } from '../../api/client';
import { dailyLimitProblem, formatReset, refusalFor } from './refusals';

function apiError(code: string, detail: string, extra: Partial<Problem> = {}) {
  return new ApiError({ type: '', title: '', status: 422, detail, code, ...extra });
}

test('the reset time is shown in local time, today or tomorrow', () => {
  const now = new Date(2026, 9, 3, 18, 30);
  const later = new Date(2026, 9, 3, 23, 15);
  const tomorrow = new Date(2026, 9, 4, 6, 0);
  expect(formatReset(later.toISOString(), now)).toBe('at 23:15 today');
  expect(formatReset(tomorrow.toISOString(), now)).toBe('at 06:00 tomorrow');
  expect(formatReset(new Date(2026, 9, 6, 6, 0).toISOString(), now)).toBe('at 06:00 on 6 Oct');
});

test('the daily limit names the limit and when to come back', () => {
  const now = new Date(2026, 9, 3, 18, 30);
  const resets = new Date(2026, 9, 4, 6, 0).toISOString();
  expect(
    dailyLimitProblem(
      { used_seconds: 7200, limit_seconds: 7200, clips_in_progress: 0, resets_at: resets },
      now,
    ),
  ).toEqual({
    title: "You have reached today's limit of new audio",
    detail:
      'You have added 120 minutes of new audio today, the daily limit. You can add more at 06:00 tomorrow.',
  });
  expect(
    dailyLimitProblem(
      { used_seconds: 3600, limit_seconds: 7200, clips_in_progress: 4, resets_at: resets },
      now,
    ).title,
  ).toBe('Wait for your clips in progress');
});

test.each([
  ['unsupported_file_type', "This file type can't be used"],
  ['file_too_large', 'This file is too large'],
  ['storage_full', 'Your upload storage is full'],
  ['upload_size_mismatch', 'The upload did not go through'],
  ['upload_expired', 'The upload did not go through'],
])('the server refusal %s gets its own title', (code, title) => {
  const refusal = refusalFor(apiError(code, 'The details. What to do next.'));
  expect(refusal).toEqual({ title, detail: 'The details. What to do next.' });
});

test('too many uploads says to wait', () => {
  expect(refusalFor(apiError('rate_limited', 'Too many requests. Try again later.'))).toEqual({
    title: 'Too many uploads at once',
    detail: 'You have started many uploads in a short time. Wait a few minutes, then try again.',
  });
});

test('other errors are left to the error panel', () => {
  expect(refusalFor(apiError('internal_error', 'Boom'))).toBeNull();
  expect(refusalFor(new TypeError('offline'))).toBeNull();
});
