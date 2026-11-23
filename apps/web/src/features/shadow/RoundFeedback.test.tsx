import { screen, within } from '@testing-library/react';
import { jsonResponse, renderWithProviders } from '../../test-utils';
import { mockRoutes } from '../session/testApi';
import { SCORED_ROUND as SCORED } from './fixtures';
import { RoundFeedback } from './RoundFeedback';

afterEach(() => vi.restoreAllMocks());

function renderFeedback(body: unknown, showMarkers = true) {
  mockRoutes({ 'GET /shadow/rounds/r2/grade': jsonResponse(200, body) });
  return renderWithProviders(<RoundFeedback roundId="r2" round={2} showMarkers={showMarkers} />);
}

test('an unavailable grade says so, exactly as before grading ships (E2)', async () => {
  renderFeedback({ status: 'unavailable' });
  expect(await screen.findByText('Feedback unavailable.')).toBeInTheDocument();
  expect(screen.queryByRole('region', { name: 'Round 2 word markers' })).not.toBeInTheDocument();
});

test('a failed read also reads as unavailable and never shows numbers', async () => {
  mockRoutes({});
  renderWithProviders(<RoundFeedback roundId="r2" round={2} showMarkers />);
  expect(await screen.findByText('Feedback unavailable.')).toBeInTheDocument();
  expect(screen.queryByText(/\/ 100/)).not.toBeInTheDocument();
});

test('a scored round shows the six measures and the overall without accent', async () => {
  renderFeedback(SCORED);
  expect(await screen.findByText('Round 2 score: 75 / 100')).toBeInTheDocument();
  const list = screen.getByRole('list', { name: 'Round 2 measures' });
  expect(
    within(list)
      .getAllByRole('listitem')
      .map((item) => item.textContent),
  ).toEqual([
    'Rhythm and timing: 80 / 100',
    'Pronunciation: 70 / 100',
    'Articulation: 60 / 100',
    'Fluency: 90 / 100',
    'Filler words: 100 / 100',
    'Completeness: not measured',
  ]);
  expect(within(list).queryByText(/accent/i)).not.toBeInTheDocument();
});

test('accent stands apart as experimental guidance compared with this speaker', async () => {
  renderFeedback(SCORED);
  const block = await screen.findByRole('region', { name: 'Round 2 accent guidance' });
  expect(within(block).getByText('Experimental')).toBeInTheDocument();
  expect(within(block).getByText('Not in your score')).toBeInTheDocument();
  expect(within(block).getByText('Compared with this speaker: 42 / 100')).toBeInTheDocument();
  expect(block).toHaveTextContent('guidance, not a judgement of correct English');
  expect(block).not.toHaveTextContent(/correct(ness)? score|wrong|error/i);
});

test('accent with nothing to compare says so instead of a number', async () => {
  renderFeedback({ ...SCORED, accent: { ...SCORED.accent, score: null, reason: 'x' } });
  const block = await screen.findByRole('region', { name: 'Round 2 accent guidance' });
  expect(within(block).getByText('Not enough speech to compare with this speaker.')).toBeVisible();
});

test('every word carries its marker in words, not colour alone (FR-SH-10, UX-01)', async () => {
  renderFeedback(SCORED);
  const markers = await screen.findByRole('region', { name: 'Round 2 word markers' });
  const transcript = within(markers).getByLabelText('Segment transcript with word markers');
  // Screen readers hear each marked word's label; sighted learners see a line style or glyph.
  expect(transcript).toHaveTextContent('Hello world. (needs work) ○ Again. (missed)');
  const needsWork = within(transcript).getByText('world.');
  expect(needsWork).toHaveClass('decoration-dotted');
  const missed = within(transcript).getByText('Again.');
  expect(missed.closest('[data-label="missed"]')).toHaveTextContent('○');
  expect(within(markers).getByText(/Words with no mark sounded good/)).toBeInTheDocument();
});

test('words to work on list their sound-level reasons in plain words', async () => {
  renderFeedback(SCORED);
  const list = await screen.findByRole('list', { name: 'Round 2 words to work on' });
  expect(
    within(list)
      .getAllByRole('listitem')
      .map((item) => item.textContent),
  ).toEqual([
    'world.: ending sound “d” dropped, where it links to the next word',
    'Again.: missed',
  ]);
});

test.each([
  ['initial', 'merged', false, 'start sound “k” merged into a neighbouring sound'],
  ['medial', 'unclear', false, 'middle sound “k” unclear'],
  [
    'initial',
    'inaccurate',
    true,
    'start sound “k” not quite right, where it links from the word before',
  ],
] as const)('reason %s %s reads plainly', async (position, issue, linking, text) => {
  renderFeedback({
    ...SCORED,
    word_labels: [
      {
        index: 0,
        text: 'cat',
        label: 'needs_work',
        score: 40,
        reasons: [{ sound: 'k', position, issue, linking }],
      },
    ],
  });
  const list = await screen.findByRole('list', { name: 'Round 2 words to work on' });
  expect(list).toHaveTextContent(`cat: ${text}`);
});

test('a needs-work word without sound detail still says why', async () => {
  renderFeedback({
    ...SCORED,
    word_labels: [{ index: 0, text: 'cat', label: 'needs_work', score: 50, reasons: [] }],
  });
  const list = await screen.findByRole('list', { name: 'Round 2 words to work on' });
  expect(list).toHaveTextContent('cat: needs work');
});

test('markers stay hidden while another round is being shadowed', async () => {
  renderFeedback(SCORED, false);
  expect(await screen.findByText('Round 2 score: 75 / 100')).toBeInTheDocument();
  expect(screen.queryByLabelText('Segment transcript with word markers')).not.toBeInTheDocument();
  expect(
    screen.getByText('Word markers come back when the current round ends.'),
  ).toBeInTheDocument();
});
