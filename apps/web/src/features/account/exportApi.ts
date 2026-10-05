import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '../../api/client';
import type { components } from '../../api/schema';

export type DataExport = components['schemas']['DataExport'];
type LatestExport = components['schemas']['LatestExport'];

/** The learner's latest data export; `export.ready` refetches it (ADR 0030). */
export const EXPORTS_KEY = ['exports'] as const;
const LATEST_KEY = [...EXPORTS_KEY, 'latest'] as const;

/** How often an export being prepared is checked when no live event arrives. */
export const EXPORT_POLL_MS = 5000;

export function isPreparing(status: DataExport['status']): boolean {
  return status === 'pending' || status === 'building';
}

export function useLatestExport() {
  return useQuery({
    queryKey: LATEST_KEY,
    queryFn: () => api<LatestExport>('/me/exports/latest'),
    refetchInterval: (query) => {
      const status = query.state.data?.export?.status;
      return status !== undefined && isPreparing(status) ? EXPORT_POLL_MS : false;
    },
  });
}

/** Ask for a new export (`POST /me/exports`); the answer becomes the latest export. */
export function useRequestExport() {
  const queryClient = useQueryClient();
  return useMutation({
    // A second click while one is prepared answers 409 `export_in_progress`.
    mutationFn: () => api<DataExport>('/me/exports', { method: 'POST' }),
    onSuccess: (started) => {
      queryClient.setQueryData<LatestExport>(LATEST_KEY, { export: started });
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: EXPORTS_KEY }),
  });
}
