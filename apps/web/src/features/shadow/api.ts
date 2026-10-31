import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CONSENT_VERSIONS_KEY, MY_CONSENTS_KEY } from '../../auth/consentApi';
import { api, ApiError } from '../../api/client';
import type { components } from '../../api/schema';
import { sessionKey, type Session, SESSIONS_KEY } from '../session/api';

export type Segment = components['schemas']['Segment'];
const key = (id: string) => [...SESSIONS_KEY, id, 'shadow', 'segment'];
const path = (id: string) => `/sessions/${encodeURIComponent(id)}/shadow/segment`;
export function useSegment(id: string) {
  return useQuery({ queryKey: key(id), queryFn: () => api<Segment>(path(id)) });
}
export function useSaveSegment(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: components['schemas']['SegmentChoice']) =>
      api<Segment>(path(id), { method: 'PUT', body }),
    onSuccess: (value) => client.setQueryData(key(id), value),
  });
}

export type Rounds = components['schemas']['Rounds'];
export const roundsKey = (id: string) => [...SESSIONS_KEY, id, 'shadow', 'rounds'];
export function useRounds(id: string) {
  return useQuery({
    queryKey: roundsKey(id),
    queryFn: () => api<Rounds>(`/sessions/${encodeURIComponent(id)}/shadow/rounds`),
    staleTime: 0,
    gcTime: 0,
  });
}
export function useChangeRound(id: string) {
  const client = useQueryClient();
  const discardTranscript = async () => {
    await client.cancelQueries({ queryKey: roundsKey(id) });
    client.setQueryData<Rounds>(roundsKey(id), (value) =>
      value ? { ...value, text: undefined } : value,
    );
  };
  return useMutation({
    mutationFn: async ({
      number,
      action,
    }: {
      number: number;
      action: 'start' | 'playback-ended';
    }) => {
      await api(`/sessions/${encodeURIComponent(id)}/shadow/rounds/${number}/${action}`, {
        method: 'POST',
        headers: { 'Idempotency-Key': `shadow-${id}-${number}-${action}` },
      });
    },
    onMutate: discardTranscript,
    onError: async (error) => {
      if (error instanceof ApiError && error.code === 'voice_consent_required') {
        await Promise.all([
          client.resetQueries({ queryKey: MY_CONSENTS_KEY }),
          client.invalidateQueries({ queryKey: CONSENT_VERSIONS_KEY }),
        ]);
      }
    },
    onSettled: async () => {
      // A focus refetch may have restored round-1 data while the write was pending.
      // Cancel it before clearing, so a late response cannot restore that text.
      await discardTranscript();
      await Promise.all([
        client.invalidateQueries({ queryKey: roundsKey(id) }),
        client.invalidateQueries({ queryKey: key(id) }),
      ]);
    },
  });
}

export const RECORDING_MAX_BYTES = 5 * 1024 * 1024;

/**
 * Ask for a signed URL, send the blob straight to storage, then mark the round
 * recorded. Every step can be repeated with the same blob (FR-SH-8).
 */
export function useUploadRecording(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({
      number,
      recording,
    }: {
      number: number;
      recording: { blob: Blob; mime: string };
    }) => {
      const session =
        client.getQueryData<Session>(sessionKey(id)) ??
        (await api<Session>(`/sessions/${encodeURIComponent(id)}`));
      let started;
      try {
        started = await api<components['schemas']['RecordingUpload']>(
          `/sessions/${encodeURIComponent(id)}/shadow/rounds/${number}/recording`,
          { method: 'POST', body: { mime: recording.mime, size_bytes: recording.blob.size } },
        );
      } catch (error) {
        // A lost response to `complete` leaves the round saved: nothing more to send.
        if (error instanceof ApiError && error.code === 'recording_exists') return;
        throw error;
      }
      const sent = await fetch(started.upload.url, {
        method: started.upload.method,
        headers: started.upload.headers,
        body: recording.blob,
      });
      if (!sent.ok) throw new Error('The recording did not reach storage.');
      await api(`/shadow/rounds/${encodeURIComponent(started.round_id)}/complete`, {
        method: 'POST',
        // The version is in the key: a retry after the session moved on is a new request.
        headers: { 'Idempotency-Key': `shadow-recording-${started.round_id}-${session.version}` },
        body: { version: session.version },
      });
    },
    onSettled: () => client.invalidateQueries({ queryKey: SESSIONS_KEY }),
  });
}

/**
 * Delete one round's recording for good (FR-SH-17). The round stays recorded, so the
 * plan's progress and any scores stay; only the replay goes.
 */
export function useDeleteRecording(sessionId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (roundId: string) =>
      api(`/shadow/rounds/${encodeURIComponent(roundId)}/recording`, { method: 'DELETE' }),
    onSuccess: () => client.invalidateQueries({ queryKey: roundsKey(sessionId) }),
  });
}
