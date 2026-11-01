import { screen } from '@testing-library/react';

import { App } from '../../App';
import { LEARNER, SIGNED_OUT, jsonResponse, mockApi, renderWithProviders } from '../../test-utils';

afterEach(() => vi.restoreAllMocks());

// #98: the accessibility statement is public, like the legal texts, and honest about
// what has and has not been checked.
test('the accessibility statement is public and names its target and limits', async () => {
  mockApi({ '/me': SIGNED_OUT });
  renderWithProviders(<App />, { route: '/accessibility' });

  expect(
    await screen.findByRole('heading', { level: 1, name: 'Accessibility statement' }),
  ).toBeInTheDocument();
  expect(document.title).toBe('Accessibility statement · ListenUp');
  expect(screen.getByText(/WCAG\) 2\.1 at level AA/)).toBeInTheDocument();
  expect(screen.getByRole('heading', { level: 2, name: 'Known limitations' })).toBeInTheDocument();
  // Not claimed: the manual screen-reader passes have not been done yet.
  expect(screen.getByText(/partially conformant/i)).toBeInTheDocument();
  expect(screen.getByText(/screen reader.*not yet/i)).toBeInTheDocument();
  expect(screen.getByRole('note')).toHaveTextContent('Draft');
});

test('settings link to the accessibility statement', async () => {
  mockApi({
    '/me': jsonResponse(200, LEARNER),
    '/me/consents': jsonResponse(200, { consents: [], current: {} }),
    '/me/exports/latest': jsonResponse(200, { export: null }),
  });
  renderWithProviders(<App />, { route: '/settings' });

  expect(await screen.findByRole('link', { name: 'Accessibility statement' })).toHaveAttribute(
    'href',
    '/accessibility',
  );
});
