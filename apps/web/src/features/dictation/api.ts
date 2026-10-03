import { useQuery } from '@tanstack/react-query';

import { api, ApiError } from '../../api/client';
import type { components } from '../../api/schema';
import { SaveConflict, type SaveResult } from '../../lib/autosave';
import { SESSIONS_KEY } from '../session/api';

export type DictationAttempt = components['schemas']['DictationAttempt'];
type SavedDraft = components['schemas']['SavedDraft'];

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
