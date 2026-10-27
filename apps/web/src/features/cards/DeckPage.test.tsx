import { fireEvent, screen, waitFor } from '@testing-library/react';
import { jsonResponse, renderWithProviders } from '../../test-utils';
import { mockRoutes } from '../session/testApi';
import DeckPage from './DeckPage';

const card = {
  id: 'c1',
  session_id: 's1',
  written_form: 'could have',
  heard_form: 'kuduv',
  audio_status: 'ready',
  source_url: '/contents/clip-1?at_ms=11000',
};
beforeEach(() => {
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue();
});
afterEach(() => vi.restoreAllMocks());
it('keeps both forms and labels hidden until snippet ends and saves a result', async () => {
  let saved: unknown;
  mockRoutes({
    'GET /cards': jsonResponse(200, { cards: [card], next_cursor: null }),
    'GET /cards/c1/reviews': jsonResponse(200, { reviews: [] }),
    'POST /cards/c1/reviews': ({ body }) => {
      saved = body;
      return jsonResponse(201, { result: 'unsure' });
    },
  });
  const { container } = renderWithProviders(<DeckPage />);
  const reveal = await screen.findByRole('button', { name: 'Reveal forms' });
  expect(reveal).toBeDisabled();
  expect(screen.queryByText('could have')).not.toBeInTheDocument();
  expect(container.innerHTML).not.toContain('kuduv');
  fireEvent.click(screen.getByRole('button', { name: 'Play snippet' }));
  await waitFor(() => expect(HTMLMediaElement.prototype.play).toHaveBeenCalled());
  expect(reveal).toBeDisabled();
  fireEvent.ended(container.querySelector('audio')!);
  fireEvent.click(reveal);
  expect(screen.getByText('could have')).toBeVisible();
  expect(screen.getByText('kuduv')).toBeVisible();
  expect(screen.getByRole('link', { name: 'Open source' })).toHaveAttribute(
    'href',
    card.source_url,
  );
  const unsure = screen.getByRole('button', { name: 'Unsure' });
  unsure.focus();
  fireEvent.click(unsure);
  await screen.findByText('Saved: unsure');
  expect(unsure).not.toBeDisabled();
  expect(unsure).toHaveAttribute('aria-disabled', 'true');
  expect(unsure).toHaveFocus();
  expect(saved).toEqual({ result: 'unsure' });
});

it('resets reveal when moving through paginated cards and pauses abandoned audio', async () => {
  mockRoutes({
    'GET /cards': jsonResponse(200, { cards: [card], next_cursor: 'next' }),
    'GET /cards?cursor=next': jsonResponse(200, {
      cards: [{ ...card, id: 'c2', written_form: 'want to' }],
      next_cursor: null,
    }),
    'GET /cards/c1/reviews': jsonResponse(200, { reviews: [] }),
    'GET /cards/c2/reviews': jsonResponse(200, { reviews: [] }),
  });
  const { container } = renderWithProviders(<DeckPage />);
  await screen.findByRole('button', { name: 'Play snippet' });
  fireEvent.ended(container.querySelector('audio')!);
  fireEvent.click(screen.getByRole('button', { name: 'Reveal forms' }));
  fireEvent.click(screen.getByRole('button', { name: 'Load more cards' }));
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Next card' })).toHaveAttribute(
      'aria-disabled',
      'false',
    ),
  );
  fireEvent.click(screen.getByRole('button', { name: 'Next card' }));
  expect(screen.queryByText('could have')).not.toBeInTheDocument();
  expect(screen.queryByText('want to')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Reveal forms' })).toBeDisabled();
  expect(HTMLMediaElement.prototype.pause).toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Previous card' }));
  expect(screen.getByRole('button', { name: 'Reveal forms' })).toBeDisabled();
});

it('keeps reveal locked on playback failure, permits retry, pause and saved history', async () => {
  const play = vi
    .mocked(HTMLMediaElement.prototype.play)
    .mockRejectedValueOnce(new Error('offline'));
  mockRoutes({
    'GET /cards': jsonResponse(200, { cards: [card], next_cursor: null }),
    'GET /cards/c1/reviews': jsonResponse(200, {
      reviews: [{ id: 'r1', result: 'missed', reviewed_at: '2026-10-26T10:00:00Z' }],
    }),
    'POST /cards/c1/reviews': jsonResponse(500, {
      code: 'unavailable',
      detail: 'Could not save result',
    }),
  });
  const { container } = renderWithProviders(<DeckPage />);
  fireEvent.click(await screen.findByRole('button', { name: 'Play snippet' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('could not play');
  expect(screen.getByRole('button', { name: 'Reveal forms' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Play snippet' }));
  await waitFor(() => expect(play).toHaveBeenCalledTimes(2));
  fireEvent.playing(container.querySelector('audio')!);
  fireEvent.click(screen.getByRole('button', { name: 'Pause snippet' }));
  fireEvent.pause(container.querySelector('audio')!);
  fireEvent.error(container.querySelector('audio')!);
  expect(screen.getByRole('button', { name: 'Reveal forms' })).toBeDisabled();
  fireEvent.ended(container.querySelector('audio')!);
  fireEvent.click(screen.getByRole('button', { name: 'Reveal forms' }));
  expect(await screen.findByRole('heading', { name: 'Recent results' })).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Missed' }));
  expect(await screen.findByText('Could not save result')).toBeVisible();
  expect(screen.getByRole('button', { name: 'Missed' })).toBeEnabled();
});

it.each(['pending', 'unavailable', 'failed'])(
  'handles %s audio without exposing forms',
  async (status) => {
    mockRoutes({
      'GET /cards': jsonResponse(200, {
        cards: [{ ...card, audio_status: status }],
        next_cursor: null,
      }),
      'GET /cards/c1/reviews': jsonResponse(200, { reviews: [] }),
      'POST /cards/c1/audio/retry': jsonResponse(500, { code: 'failed', detail: 'Retry failed' }),
    });
    renderWithProviders(<DeckPage />);
    expect(await screen.findByRole('button', { name: 'Play snippet' })).toBeDisabled();
    expect(screen.queryByText('could have')).not.toBeInTheDocument();
    if (status === 'failed') {
      fireEvent.click(screen.getByRole('button', { name: 'Retry audio' }));
      expect(await screen.findByRole('alert')).toHaveTextContent('Retry failed');
    }
  },
);

it('shows empty and failed deck states', async () => {
  mockRoutes({ 'GET /cards': jsonResponse(200, { cards: [], next_cursor: null }) });
  const view = renderWithProviders(<DeckPage />);
  expect(await screen.findByText(/No saved cards yet/)).toBeVisible();
  view.unmount();
  mockRoutes({
    'GET /cards': jsonResponse(500, { code: 'unavailable', detail: 'Deck unavailable' }),
  });
  renderWithProviders(<DeckPage />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Deck unavailable');
});

it('keeps the next control available to keyboard users at the end of the deck', async () => {
  mockRoutes({
    'GET /cards': jsonResponse(200, { cards: [card, { ...card, id: 'c2' }], next_cursor: null }),
    'GET /cards/c1/reviews': jsonResponse(200, { reviews: [] }),
    'GET /cards/c2/reviews': jsonResponse(200, { reviews: [] }),
  });
  renderWithProviders(<DeckPage />);
  const next = await screen.findByRole('button', { name: 'Next card' });
  next.focus();
  fireEvent.click(next);
  expect(screen.getByRole('button', { name: 'Next card' })).toHaveFocus();
  expect(next).toHaveAttribute('aria-disabled', 'true');
  fireEvent.click(next);
  expect(screen.getByText('Card 2 of 2')).toBeVisible();
});

it('refreshes failed snippet status after a successful retry', async () => {
  let status = 'failed';
  mockRoutes({
    'GET /cards': () =>
      jsonResponse(200, { cards: [{ ...card, audio_status: status }], next_cursor: null }),
    'GET /cards/c1/reviews': jsonResponse(200, { reviews: [] }),
    'POST /cards/c1/audio/retry': () => {
      status = 'ready';
      return new Response(null, { status: 202 });
    },
  });
  renderWithProviders(<DeckPage />);
  fireEvent.click(await screen.findByRole('button', { name: 'Retry audio' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Play snippet' })).toBeEnabled());
  expect(screen.getByRole('button', { name: 'Reveal forms' })).toBeDisabled();
});
