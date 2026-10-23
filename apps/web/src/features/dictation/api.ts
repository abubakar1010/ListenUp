import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef } from 'react';

import { api, ApiError } from '../../api/client';
import type { components } from '../../api/schema';
import { SaveConflict, type SaveResult } from '../../lib/autosave';
import type { Range } from '../review/selection';
import { SESSIONS_KEY, SESSIONS_LIST_KEY, sessionKey } from '../session/api';

export type DictationAttempt = components['schemas']['DictationAttempt'];
type SavedDraft = components['schemas']['SavedDraft'];
export type DictationResult = components['schemas']['DictationResult'];
export type DictationAttemptView = components['schemas']['DictationAttemptView'];
export type DictationSubmission = components['schemas']['DictationSubmission'];
export type DiffItem = components['schemas']['DiffItem'];

export const dictationKey = (sessionId: string) =>
  [...SESSIONS_KEY, 'dictation', sessionId] as const;

/**
 * Start the session's Dictation attempt, or resume the one in progress with its draft
 * (#51, #50). Asked again on every visit, so the draft is the server's latest.
 */
export function useDictationAttempt(sessionId: string) {
  return useQuery({
    queryKey: dictationKey(sessionId),
    queryFn: () =>
      api<DictationAttempt>(`/sessions/${encodeURIComponent(sessionId)}/dictation/attempts`, {
        method: 'POST',
      }),
    staleTime: Infinity,
    gcTime: 0,
    refetchOnWindowFocus: false,
  });
}

/** Record the first playback, rather than merely opening the Dictation screen. */
export function recordListenStarted(attemptId: string): Promise<void> {
  return api<void>(`/dictation/attempts/${encodeURIComponent(attemptId)}/listen`, {
    method: 'POST',
  });
}

/**
 * Save the draft on the version it was based on. A newer draft on the server (another
 * tab or browser) comes back as `SaveConflict` with that draft (#50).
 */
export async function saveDraft(
  attemptId: string,
  text: string,
  baseVersion: number,
): Promise<SaveResult> {
  try {
    const saved = await api<SavedDraft>(
      `/dictation/attempts/${encodeURIComponent(attemptId)}/draft`,
      { method: 'PUT', body: { draft_text: text, draft_version: baseVersion } },
    );
    return { version: saved.draft_version, savedAt: new Date(saved.updated_at) };
  } catch (error) {
    if (error instanceof ApiError && error.code === 'draft_conflict') {
      const { draft_text: theirs, draft_version: version } = error.problem;
      throw new SaveConflict(String(theirs ?? ''), Number(version));
    }
    throw error;
  }
}

/** Where the unsent draft is kept on this device. */
export const draftStorageKey = (attemptId: string) => `listenup:dictation-draft:${attemptId}`;

export const MAX_DRAFT_CHARS = 20_000;

/**
 * Every Dictation result, for the `dictation.scored` event, which names only the attempt.
 * Separate from `dictationKey` so the event never refetches the attempt-opening request.
 */
export const DICTATION_RESULT_KEY = [...SESSIONS_KEY, 'dictation-result'] as const;
export const dictationResultKey = (sessionId: string) =>
  [...DICTATION_RESULT_KEY, sessionId] as const;

/**
 * The session's Dictation attempt with its score once scored (FR-DI-5). 404
 * `attempt_not_found` when Dictation was never started: nothing to show.
 */
export function useDictationResult(sessionId: string) {
  return useQuery({
    queryKey: dictationResultKey(sessionId),
    queryFn: () =>
      api<DictationAttemptView>(`/sessions/${encodeURIComponent(sessionId)}/dictation/attempt`),
    retry: false,
    // Results of sessions no longer on screen are dropped soon, so `dictation.scored` and a
    // resync refetch only what is shown, not every session the learner has visited.
    gcTime: 30_000,
  });
}

/**
 * Submit the text (FR-DI-5). One Idempotency-Key per attempt, so a retry after a lost
 * answer returns the first answer. The session refetches: the Dictation step is complete.
 */
export function useSubmitDictation(sessionId: string, attemptId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { text: string; version: number; replayCount: number }) =>
      api<DictationSubmission>(`/dictation/attempts/${encodeURIComponent(attemptId)}/submit`, {
        method: 'POST',
        body: { text: input.text, version: input.version, replay_count: input.replayCount },
        headers: { 'Idempotency-Key': `dictation-${attemptId}` },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: sessionKey(sessionId) });
      void queryClient.invalidateQueries({ queryKey: SESSIONS_LIST_KEY });
    },
  });
}

export type DictationMark = components['schemas']['DictationMark'];
type DictationMarks = components['schemas']['DictationMarks'];

export const dictationMarksKey = (attemptId: string) =>
  [...SESSIONS_KEY, 'dictation-marks', attemptId] as const;

const marksPath = (attemptId: string) =>
  `/dictation/attempts/${encodeURIComponent(attemptId)}/marks`;

/**
 * A mark list the page already keeps, such as Transcript's `MarkSync` (#55). The Dictation
 * result shows its marks as added and hands it the marks it adds, so both agree.
 */
export interface OpenMarkList {
  marks: Range[];
  take: (marks: DictationMark[]) => void;
}

/**
 * The session's marks, so the diff shows which words are already added (#55). Not read
 * while the page keeps its own list (`enabled: false`).
 */
export function useDictationMarks(attemptId: string, enabled = true) {
  return useQuery({
    queryKey: dictationMarksKey(attemptId),
    queryFn: async () => (await api<DictationMarks>(marksPath(attemptId))).marks,
    enabled,
  });
}

/**
 * Add words of the diff to the mark list (FR-DI-6). The browser names each mark and a
 * range keeps its id until it is added, so a retry after a lost answer is the same mark
 * (ADR 0047); words that are already marked come back as the mark they have.
 */
export function useAddDictationMarks(
  attemptId: string,
  onAdded?: (marks: DictationMark[]) => void,
) {
  const queryClient = useQueryClient();
  const ids = useRef(new Map<string, string>());
  const idFor = (range: Range) => {
    const key = `${range.word_from}-${range.word_to}`;
    let id = ids.current.get(key);
    if (!id) {
      id = crypto.randomUUID();
      ids.current.set(key, id);
    }
    return id;
  };
  return useMutation({
    mutationFn: async (ranges: Range[]) =>
      (
        await api<DictationMarks>(marksPath(attemptId), {
          method: 'POST',
          body: {
            marks: ranges.map(({ word_from, word_to }) => ({
              id: idFor({ word_from, word_to }),
              word_from,
              word_to,
            })),
          },
        })
      ).marks,
    onSuccess: (marks) => {
      queryClient.setQueryData<DictationMark[]>(dictationMarksKey(attemptId), (known = []) => {
        const byId = new Map(known.map((mark) => [mark.id, mark]));
        for (const mark of marks) byId.set(mark.id, mark);
        return [...byId.values()];
      });
      onAdded?.(marks);
    },
  });
}
