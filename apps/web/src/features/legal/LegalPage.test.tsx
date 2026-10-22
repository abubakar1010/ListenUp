import { screen } from '@testing-library/react';

import { App } from '../../App';
import { DOCUMENTS } from '../../auth/consentApi';
import { SIGNED_OUT, jsonResponse, mockApi, renderWithProviders } from '../../test-utils';

const VERSIONS = {
  terms: 'terms-2026-1',
  privacy: 'privacy-2026-1',
  voice_recording: 'voice-2026-1',
};

afterEach(() => vi.restoreAllMocks());

function serve(versions: object) {
  mockApi({ '/me': SIGNED_OUT, '/auth/consent-versions': jsonResponse(200, versions) });
}

test.each([
  ['/terms', 'Terms of Service', 'terms-2026-1', 'Takedowns'],
  ['/privacy', 'Privacy Policy', 'privacy-2026-1', 'How long we keep it'],
  ['/voice-consent', 'Voice recording consent', 'voice-2026-1', 'Never used for training'],
])('%s shows the text of the version learners accept now', async (route, name, label, section) => {
  serve(VERSIONS);
  renderWithProviders(<App />, { route });

  expect(await screen.findByRole('heading', { level: 1, name })).toBeInTheDocument();
  expect(screen.getByText(new RegExp(`^Version ${label},`))).toBeInTheDocument();
  expect(screen.getByRole('heading', { level: 2, name: section })).toBeInTheDocument();
  // Every 2026-1 text is a draft for legal review (#103), and says so.
  expect(screen.getByRole('note')).toHaveTextContent('Draft, not yet legally reviewed.');
  expect(document.title).toBe(`${name} · ListenUp`);
});

test('says so instead of showing another text when the current version has none here', async () => {
  serve({ ...VERSIONS, privacy: 'privacy-2027-1' });
  renderWithProviders(<App />, { route: '/privacy' });

  expect(await screen.findByRole('heading', { level: 1, name: 'Privacy Policy' })).toBeVisible();
  expect(screen.getByRole('alert')).toHaveTextContent(
    'The text of version privacy-2027-1 is not available here.',
  );
  expect(screen.queryByText(/^Version privacy-2026-1,/)).not.toBeInTheDocument();
});

test('the voice recording consent links to its own page', () => {
  expect(DOCUMENTS.voice_recording.path).toBe('/voice-consent');
});

test('says why when the current versions cannot be loaded', async () => {
  mockApi({ '/me': SIGNED_OUT });
  renderWithProviders(<App />, { route: '/terms' });

  expect(await screen.findByRole('alert')).toHaveTextContent(`No mock for /auth/consent-versions.`);
  expect(screen.getByRole('heading', { level: 1, name: 'Terms of Service' })).toBeVisible();
});
