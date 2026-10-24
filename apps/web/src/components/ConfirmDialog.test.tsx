import { fireEvent, render, screen } from '@testing-library/react';

import { ConfirmDialog } from './ConfirmDialog';

test('pending dialogs retain focus and keyboard navigation when every control is disabled', () => {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  const dialog = (busy: boolean) => (
    <ConfirmDialog
      title="Save correction"
      confirmLabel="Save"
      cancelLabel="Cancel"
      onConfirm={onConfirm}
      onCancel={onCancel}
      busy={busy}
    >
      <input aria-label="Corrected text" disabled={busy} />
    </ConfirmDialog>
  );
  const { rerender } = render(dialog(false));
  expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus();
  screen.getByRole('button', { name: 'Save' }).focus();

  rerender(dialog(true));

  const modal = screen.getByRole('dialog');
  expect(modal).toHaveFocus();
  expect(fireEvent.keyDown(modal, { key: 'Tab' })).toBe(false);
  expect(modal).toHaveFocus();
  expect(fireEvent.keyDown(modal, { key: 'Tab', shiftKey: true })).toBe(false);
  expect(modal).toHaveFocus();
  fireEvent.keyDown(modal, { key: 'Escape' });
  expect(onCancel).not.toHaveBeenCalled();
  expect(onConfirm).not.toHaveBeenCalled();

  rerender(dialog(false));
  expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus();
  fireEvent.keyDown(modal, { key: 'Escape' });
  expect(onCancel).toHaveBeenCalledOnce();
});
