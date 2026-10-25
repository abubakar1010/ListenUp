import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';

import { Sheet } from './Sheet';

function Harness() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open
      </button>
      {open && (
        <Sheet title="Your plan" onClose={() => setOpen(false)}>
          <a href="#first">First link</a>
          <button type="button">Last button</button>
        </Sheet>
      )}
    </>
  );
}

function openSheet() {
  render(<Harness />);
  const opener = screen.getByRole('button', { name: 'Open' });
  opener.focus();
  fireEvent.click(opener);
  return { opener, sheet: screen.getByRole('dialog', { name: 'Your plan' }) };
}

test('focus starts on Close and Tab wraps inside the sheet both ways', () => {
  const { sheet } = openSheet();
  const close = screen.getByRole('button', { name: 'Close' });
  const last = screen.getByRole('button', { name: 'Last button' });
  expect(close).toHaveFocus();
  expect(sheet).toHaveAttribute('aria-modal', 'true');

  fireEvent.keyDown(sheet, { key: 'Tab', shiftKey: true });
  expect(last).toHaveFocus();
  fireEvent.keyDown(sheet, { key: 'Tab' });
  expect(close).toHaveFocus();

  // Tab between the ends is left to the browser.
  screen.getByRole('link', { name: 'First link' }).focus();
  fireEvent.keyDown(sheet, { key: 'Tab' });
  expect(screen.getByRole('link', { name: 'First link' })).toHaveFocus();
  fireEvent.keyDown(sheet, { key: 'Enter' });
  expect(sheet).toBeInTheDocument();
});

test('a press inside the sheet keeps it open; the scrim closes it and focus returns', async () => {
  const { opener, sheet } = openSheet();

  fireEvent.mouseDown(sheet);
  expect(screen.getByRole('dialog')).toBeInTheDocument();

  fireEvent.mouseDown(screen.getByTestId('sheet-scrim'));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  await waitFor(() => expect(opener).toHaveFocus());
});

test('focus that has left the sheet is brought back by Tab', () => {
  const { sheet } = openSheet();
  document.body.focus();

  fireEvent.keyDown(sheet, { key: 'Tab' });
  expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus();
});
