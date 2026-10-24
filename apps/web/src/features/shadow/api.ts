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
