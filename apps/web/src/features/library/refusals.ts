/*
 * Why a file cannot be added, in the learner's words (FR-CI-3, NFR-USE-3, #39, #41).
 * Each message says what happened and what to do next. The page checks what it can
 * before any byte is sent (type, size, storage, today's new audio); the server checks
 * again and its refusals are turned into the same kind of message here.
 */
import { ApiError } from '../../api/client';
import type { components } from '../../api/schema';
import { formatSize, type FileProblem } from './files';

export type DailyAudio = components['schemas']['DailyAudio'];

function minutes(seconds: number): string {
  const whole = Math.floor(seconds / 60);
  return whole === 1 ? '1 minute' : `${whole} minutes`;
}

function sameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

/**
 * When the daily count resets, in the learner's own time: "at 06:00 tomorrow". The
 * server counts UTC days (ADR 0027), so for most learners this is not their midnight.
 */
export function formatReset(iso: string, now: Date = new Date()): string {
  const reset = new Date(iso);
  const time = reset.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  if (sameDay(reset, now)) return `at ${time} today`;
  const tomorrow = new Date(now);
  tomorrow.setDate(now.getDate() + 1);
  if (sameDay(reset, tomorrow)) return `at ${time} tomorrow`;
  return `at ${time} on ${reset.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}`;
}

interface DailyFacts {
  used_seconds: number;
  limit_seconds: number;
  clips_in_progress: number;
  resets_at: string;
}

export function dailyLimitProblem(daily: DailyFacts, now: Date = new Date()): FileProblem {
  const when = formatReset(daily.resets_at, now);
  if (daily.used_seconds >= daily.limit_seconds) {
    return {
      title: "You have reached today's limit of new audio",
      detail: `You have added ${minutes(daily.limit_seconds)} of new audio today, the daily limit. You can add more ${when}.`,
    };
  }
  return {
    title: 'Wait for your clips in progress',
    detail: `The clips you are adding now may use the rest of today's ${minutes(daily.limit_seconds)} of new audio. Add this one when they are ready, or ${when}.`,
  };
}

export function storageFullProblem(name: string, size: number, used: number, quota: number) {
  return {
    title: 'Your upload storage is full',
    detail: `You have used ${formatSize(used)} of ${formatSize(quota)}, and ${name} is ${formatSize(size)}. Delete a clip you have finished to make room.`,
  } satisfies FileProblem;
}

/** A refusal before upload from what the page already knows, or null when it may go ahead. */
export function checkAllowance(
  file: File,
  usage: components['schemas']['StorageUse'] | undefined,
  now: Date = new Date(),
): FileProblem | null {
  if (!usage) return null;
  if (usage.used_bytes + file.size > usage.quota_bytes) {
    return storageFullProblem(file.name, file.size, usage.used_bytes, usage.quota_bytes);
  }
  // Older answers (and test mocks) may not report the daily allowance.
  if (usage.daily_audio && !usage.daily_audio.can_add) {
    return dailyLimitProblem(usage.daily_audio, now);
  }
  return null;
}

function isDailyFacts(problem: Record<string, unknown>): boolean {
  return (
    typeof problem.used_seconds === 'number' &&
    typeof problem.limit_seconds === 'number' &&
    typeof problem.resets_at === 'string'
  );
}

/** The server's refusal of an upload as a message for the page, or null for other errors. */
export function refusalFor(error: unknown, now: Date = new Date()): FileProblem | null {
  if (!(error instanceof ApiError)) return null;
  const { detail } = error.problem;
  switch (error.code) {
    case 'unsupported_file_type':
      return { title: "This file type can't be used", detail };
    case 'file_too_large':
      return { title: 'This file is too large', detail };
    case 'storage_full':
      return { title: 'Your upload storage is full', detail };
    case 'daily_audio_limit':
      if (isDailyFacts(error.problem)) {
        return dailyLimitProblem(
          {
            used_seconds: error.problem.used_seconds as number,
            limit_seconds: error.problem.limit_seconds as number,
            clips_in_progress: Number(error.problem.clips_in_progress ?? 0),
            resets_at: error.problem.resets_at as string,
          },
          now,
        );
      }
      return { title: "You have reached today's limit of new audio", detail };
    case 'upload_expired':
    case 'upload_incomplete':
    case 'upload_size_mismatch':
    case 'upload_not_found':
      return { title: 'The upload did not go through', detail };
    case 'rate_limited':
      return {
        title: 'Too many uploads at once',
        detail:
          'You have started many uploads in a short time. Wait a few minutes, then try again.',
      };
    default:
      return null;
  }
}
