import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import type { components } from '../../api/schema';
import { sessionKey, SESSIONS_LIST_KEY } from '../session/api';
import { LIBRARY_KEY } from '../library/useLibrary';

export type Card = components['schemas']['Card'];
export type NewCard = components['schemas']['NewCard'];
export const cardsKey = (id: string) => ['cards', id] as const;
export function useCards(id: string) {
  return useQuery({
    queryKey: cardsKey(id),
    queryFn: () =>
      api<components['schemas']['CardList']>(`/cards?session_id=${encodeURIComponent(id)}`),
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
    onSuccess: () => {
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
    onSuccess: () => {
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
