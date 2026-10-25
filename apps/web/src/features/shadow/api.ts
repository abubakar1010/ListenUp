import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import type { components } from '../../api/schema';
import { SESSIONS_KEY } from '../session/api';

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
    onMutate: async () => {
      await client.cancelQueries({ queryKey: roundsKey(id) });
      client.setQueryData<Rounds>(roundsKey(id), (value) =>
        value ? { ...value, text: undefined } : value,
      );
    },
    onSettled: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: roundsKey(id) }),
        client.invalidateQueries({ queryKey: key(id) }),
      ]);
    },
  });
}
