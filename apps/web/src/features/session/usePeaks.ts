import { useQuery } from '@tanstack/react-query';

import { parsePeaks, type Peaks } from './passage';

/** A refusal from the peaks route (404, 409 media_not_ready): asking again soon gets the same. */
class PeaksRefused extends Error {}

/**
 * The clip's waveform peaks (ADR 0022). `peaksUrl` is the API path, which redirects to a
 * signed storage URL; a media object's peaks never change, so they are fetched once.
 */
export function usePeaks(peaksUrl: string | null) {
  return useQuery({
    queryKey: ['peaks', peaksUrl],
    enabled: peaksUrl !== null,
    staleTime: Infinity,
    // Retry a network or server failure once; a refusal stands, so the picker falls back
    // to the edges and time fields straight away instead of a second later.
    retry: (failures, error) => failures < 1 && !(error instanceof PeaksRefused),
    queryFn: async (): Promise<Peaks> => {
      const response = await fetch(peaksUrl!, { credentials: 'same-origin' });
      if (!response.ok) {
        const message = `Peaks request failed with ${response.status}.`;
        throw response.status < 500 ? new PeaksRefused(message) : new Error(message);
      }
      const peaks = parsePeaks(await response.json());
      if (!peaks) throw new Error('The peaks file is not in the expected format.');
      return peaks;
    },
  });
}
