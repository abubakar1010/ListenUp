import { QueryClient, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '../api/client';
import type { components } from '../api/schema';
import { ME_KEY } from './useMe';

export type ConsentVersions = components['schemas']['ConsentVersions'];
export type Consents = components['schemas']['Consents'];
export type ConsentKind = components['schemas']['ConsentRecord']['kind'];

/** The documents' names as the learner reads them, and where their text is (#103). */
export const DOCUMENTS = {
  terms: { name: 'Terms of Service', path: '/terms' },
  privacy: { name: 'Privacy Policy', path: '/privacy' },
  voice_recording: { name: 'Voice recording consent', path: '/privacy' },
} as const;

export const CONSENT_VERSIONS_KEY = ['consents', 'versions'] as const;
export const MY_CONSENTS_KEY = ['consents', 'mine'] as const;
/** True once the server refused a request with 403 `consent_required` (ADR 0048). */
export const CONSENT_REFUSED_KEY = ['consents', 'refused'] as const;

const versionsQuery = {
  queryKey: CONSENT_VERSIONS_KEY,
  queryFn: () => api<ConsentVersions>('/auth/consent-versions'),
};

/** The versions a learner accepts now (#104); public, for the sign-up form. */
export function useConsentVersions(enabled = true) {
  return useQuery({ ...versionsQuery, enabled });
}

/**
 * Whether the server has refused a request because the learner owes a consent. The
 * query client sets it (`app/queryClient.ts`); accepting clears it.
 */
export function useConsentRefused(): boolean {
  const refused = useQuery({
    queryKey: CONSENT_REFUSED_KEY,
    queryFn: () => false,
    staleTime: Infinity,
  });
  return refused.data === true;
}

/** Remember a 403 `consent_required` and fetch `/me` again, which lists what is owed. */
export function noteConsentRefused(queryClient: QueryClient): void {
  queryClient.setQueryData(CONSENT_REFUSED_KEY, true);
  void queryClient.invalidateQueries({ queryKey: ME_KEY });
}

export function useMyConsents() {
  return useQuery({ queryKey: MY_CONSENTS_KEY, queryFn: () => api<Consents>('/me/consents') });
}

/** Accept the current version of each document, then refresh `/me` and the list. */
export function useGrantConsents() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (grants: { kind: ConsentKind; version: string }[]) => {
      let answer: Consents | undefined;
      for (const grant of grants) {
        answer = await api<Consents>('/me/consents', { method: 'POST', body: grant });
      }
      return answer;
    },
    onSuccess: (answer) => {
      if (answer) queryClient.setQueryData(MY_CONSENTS_KEY, answer);
      queryClient.setQueryData(CONSENT_REFUSED_KEY, false);
      // Requests refused while consent was owed can now succeed.
      void queryClient.invalidateQueries({ predicate: (query) => query.state.status === 'error' });
      return queryClient.invalidateQueries({ queryKey: ME_KEY });
    },
    // A newer version published meanwhile (409): show the current one.
    onError: () => queryClient.invalidateQueries({ queryKey: CONSENT_VERSIONS_KEY }),
  });
}

/** Withdraw voice-recording consent (FR-SH-17). */
export function useWithdrawConsent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (kind: ConsentKind) =>
      api<Consents>('/me/consents/withdraw', { method: 'POST', body: { kind } }),
    onSuccess: (answer) => queryClient.setQueryData(MY_CONSENTS_KEY, answer),
  });
}
