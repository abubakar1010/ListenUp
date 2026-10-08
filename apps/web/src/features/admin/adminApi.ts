import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { ApiError, api } from '../../api/client';
import type { components } from '../../api/schema';

export type JobsOverview = components['schemas']['JobsOverview'];
export type LaneBacklog = components['schemas']['LaneBacklog'];
export type FailedJob = components['schemas']['FailedJob'];
type RetriedJob = components['schemas']['RetriedJob'];

const JOBS_KEY = ['admin', 'jobs'] as const;

/** A learner who is not an administrator gets 404 `not_found` from every admin route. */
export function isNotAdmin(error: unknown): boolean {
  return error instanceof ApiError && error.code === 'not_found';
}

/** Backlog per lane and failed jobs (#100, ADR 0034). */
export function useJobsOverview() {
  return useQuery({
    queryKey: JOBS_KEY,
    queryFn: () => api<JobsOverview>('/admin/jobs'),
    retry: (failures, error) => !isNotAdmin(error) && failures < 2,
  });
}

/** Queue a failed job again; the list reloads either way. */
export function useRetryJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (jobId: number) =>
      api<RetriedJob>(`/admin/jobs/${jobId}/retry`, { method: 'POST' }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: JOBS_KEY }),
  });
}
