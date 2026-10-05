import { QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router';

import { createQueryClient } from './app/queryClient';

export function renderWithProviders(ui: ReactElement, { route = '/' } = {}) {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

export function jsonResponse(status: number, body?: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': status >= 400 ? 'application/problem+json' : 'application/json' },
  });
}

export function problem(status: number, code: string, detail: string, extra: object = {}) {
  return jsonResponse(status, {
    type: `/problems/${code}`,
    title: '',
    status,
    detail,
    code,
    ...extra,
  });
}

type Responder = Response | (() => Response);

/**
 * Mocks fetch by API path (after /api/v1). Each call gets a fresh Response, since a
 * body can be read only once. Paths without an entry answer 404.
 */
export function mockApi(routes: Record<string, Responder>) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const path = String(input).replace(/^\/api\/v1/, '');
    const responder = routes[path];
    if (!responder) return problem(404, 'not_found', `No mock for ${path}.`);
    return typeof responder === 'function' ? responder() : responder.clone();
  });
}

export const SIGNED_OUT = () => problem(401, 'not_signed_in', 'Sign in to continue.');

export const LEARNER = {
  id: '1',
  email: 'learner@example.com',
  display_name: null,
  email_verified: false,
};
