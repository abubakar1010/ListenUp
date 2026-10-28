import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import type { components } from '../../api/schema';
import { sessionKey, SESSIONS_LIST_KEY } from '../session/api';
import { LIBRARY_KEY } from '../library/useLibrary';

export type Card = components['schemas']['Card'];
export type NewCard = components['schemas']['NewCard'];
export type CardSuggestion = components['schemas']['CardSuggestion'];
type CardList = components['schemas']['CardList'];
export const cardsKey = (id: string) => ['cards', id] as const;
export function useCards(id: string) {
  return useQuery({
    queryKey: cardsKey(id),
    refetchInterval: (query) =>
      query.state.data?.cards.some((card) => card.audio_status === 'pending') ? 1000 : false,
    queryFn: () =>
      api<components['schemas']['CardList']>(`/cards?session_id=${encodeURIComponent(id)}`),
  });
}
export const suggestionsKey = (id: string) => ['card-suggestions', id] as const;
/** FR-CA-4: marks ordered with likely connected speech first; the screen works without it. */
export function useCardSuggestions(id: string) {
  return useQuery({
    queryKey: suggestionsKey(id),
    retry: false,
    // Marks are fixed once Transcript is done and earlier sessions are older still.
    staleTime: 5 * 60_000,
    queryFn: () =>
      api<components['schemas']['CardSuggestions']>(
        `/sessions/${encodeURIComponent(id)}/cards/suggestions`,
      ),
  });
}
export function useCreateCard(id: string, onCreated: () => void) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ body, key }: { body: NewCard; key: string }) =>
      api<Card>(`/sessions/${id}/cards`, {
        method: 'POST',
        body,
        headers: { 'Idempotency-Key': key },
      }),
    onSuccess: (card) => {
      // A confirmed write stays visible even if the following read fails.
      // A replay may already be present after a lost response and refetch.
      client.setQueryData<CardList>(cardsKey(id), (previous) => {
        if (!previous || previous.cards.some((saved) => saved.id === card.id)) return previous;
        return {
          ...previous,
          cards: [card, ...previous.cards],
          remaining:
            previous.remaining == null ? previous.remaining : Math.max(0, previous.remaining - 1),
        };
      });
      onCreated();
      return client.invalidateQueries({ queryKey: cardsKey(id) });
    },
    onError: () => {
      void client.invalidateQueries({ queryKey: cardsKey(id) });
      void client.invalidateQueries({ queryKey: sessionKey(id) });
    },
  });
}
export function useDeleteCard(id: string, onDeleted: () => void) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (card: string) => api<void>(`/cards/${card}`, { method: 'DELETE' }),
    onSuccess: (_data, cardId) => {
      // Remove the opener before closing its dialog, so focus falls back to main.
      client.setQueryData<CardList>(cardsKey(id), (previous) => {
        if (!previous || !previous.cards.some((saved) => saved.id === cardId)) return previous;
        return {
          ...previous,
          cards: previous.cards.filter((saved) => saved.id !== cardId),
          remaining: previous.remaining == null ? previous.remaining : previous.remaining + 1,
        };
      });
      onDeleted();
      void client.invalidateQueries({ queryKey: cardsKey(id) });
    },
    onError: () => {
      void client.invalidateQueries({ queryKey: cardsKey(id) });
    },
  });
}
export function useFinishCards(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api<void>(`/sessions/${id}/cards/complete`, {
        method: 'POST',
        headers: { 'Idempotency-Key': `cards-complete-${id}` },
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: sessionKey(id) });
      void client.invalidateQueries({ queryKey: SESSIONS_LIST_KEY });
      void client.invalidateQueries({ queryKey: LIBRARY_KEY });
    },
    onError: () => {
      void client.invalidateQueries({ queryKey: sessionKey(id) });
    },
  });
}

export function useRetryCardAudio(sessionId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api<void>(`/cards/${id}/audio/retry`, { method: 'POST' }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: cardsKey(sessionId) });
    },
  });
}
