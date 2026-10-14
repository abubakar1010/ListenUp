import type { QueryClient } from '@tanstack/react-query';

import { ApiError, type Me } from '../api/client';
import { ME_KEY } from './useMe';

/** A discarded request is an account transition, not a network outage. */
export class SessionChangedError extends ApiError {
  constructor() {
    super({
      type: 'about:blank',
      title: 'Account changed',
      status: 409,
      code: 'account_changed',
      detail:
        'The signed-in account changed while this request was pending. Refresh the page to continue.',
    });
  }
}

/** Stop outstanding reads before publishing a login, logout or completed reset. */
export function changeSession(client: QueryClient, me: Me | null): void {
  // Cancellation settles the query promise even when fetch ignores AbortSignal.
  // In particular, an old /me request must not replace the newly signed-in account.
  void client.cancelQueries();
  client.setQueryData(ME_KEY, me);
}
