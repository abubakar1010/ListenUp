import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';

import { sessionFixture } from './fixtures';
import { StepProgress } from './StepProgress';

// Both entry, Blind done, Dictation open: 5 steps.
const SESSION = sessionFixture({ entry: 'both', done: 1 });

test('the Plan button opens a sheet that names every step and its state (UX-09)', async () => {
  render(<StepProgress session={SESSION} />);
  const plan = screen.getByRole('button', { name: 'Plan' });
  expect(plan).toHaveAttribute('aria-haspopup', 'dialog');
  plan.focus();

  fireEvent.click(plan);

  const sheet = screen.getByRole('dialog', { name: 'Your plan' });
  const rows = within(sheet)
    .getAllByRole('listitem')
    .map((row) => row.textContent);
  expect(rows).toEqual([
    '1. Blind Done',
    '2. Dictation Now',
    '3. Transcript Locked',
    '4. Card Locked',
    '5. Shadow Locked',
  ]);
  expect(within(sheet).getByRole('button', { name: 'Close' })).toHaveFocus();

  fireEvent.keyDown(sheet, { key: 'Escape' });
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  await waitFor(() => expect(plan).toHaveFocus());
});

test('a skipped step reads as skipped in the sheet', () => {
  render(<StepProgress session={sessionFixture({ entry: 'blind', done: 3, skipped: ['card'] })} />);

  fireEvent.click(screen.getByRole('button', { name: 'Plan' }));

  const card = within(screen.getByRole('dialog')).getAllByRole('listitem')[2];
  expect(card).toHaveTextContent('3. Card Skipped');
});

test('the scrim and Close also close the sheet', () => {
  render(<StepProgress session={SESSION} />);

  fireEvent.click(screen.getByRole('button', { name: 'Plan' }));
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Close' }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: 'Plan' }));
  fireEvent.mouseDown(screen.getByTestId('sheet-scrim'));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});

test('without the Plan button (Blind playback), no way to open the list is shown', () => {
  render(<StepProgress session={SESSION} plan={false} />);

  expect(screen.queryByRole('button', { name: 'Plan' })).not.toBeInTheDocument();
});

test('done and current bars differ by fill, not only by hue (UX-09, WCAG 1.4.1)', () => {
  render(<StepProgress session={SESSION} />);
  const [done, open, locked] = within(screen.getByRole('list', { name: 'Plan steps' }))
    .getAllByRole('listitem')
    .map((item) => item.querySelector('[data-bar]')!);

  expect(done).toHaveAttribute('data-bar', 'soft');
  expect(open).toHaveAttribute('data-bar', 'solid');
  expect(locked).toHaveAttribute('data-bar', 'empty');
});
