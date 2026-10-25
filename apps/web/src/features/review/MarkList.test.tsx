import { fireEvent, render, screen, within } from '@testing-library/react';

import { MarkList } from './MarkList';

// Supplementary interaction coverage of the implemented list (#60, UI-4).
test('list_buttons_offer_edit_remove_and_ignore_modified_or_repeated_shortcuts', () => {
  const mark = {
    id: 'm1',
    word_from: 0,
    word_to: 0,
    at_ms: 0,
    note: null,
    source: 'manual' as const,
    status: 'confirmed' as const,
    saved: true,
  };
  const onPlay = vi.fn();
  const onEdit = vi.fn();
  const onRemove = vi.fn();
  render(
    <MarkList
      marks={[mark]}
      phraseOf={() => ''}
      onPlay={onPlay}
      onEdit={onEdit}
      onConfirm={vi.fn()}
      onRemove={onRemove}
    />,
  );
  const list = screen.getByRole('list', { name: 'Your marks' });
  // Each name starts with or contains the words on the button (WCAG 2.5.3, #98).
  const play = within(list).getByRole('button', { name: 'Play mark 00:00 · (removed words)' });
  expect(play).toHaveTextContent(/^Play mark 00:00 · \(removed words\)$/);
  fireEvent.keyDown(play, { key: 'e', ctrlKey: true });
  fireEvent.keyDown(play, { key: 'Delete', altKey: true });
  fireEvent.keyDown(play, { key: 'e', metaKey: true });
  fireEvent.keyDown(play, { key: 'Delete', repeat: true });
  fireEvent.keyDown(play, { key: 'ArrowRight' });
  expect(onEdit).not.toHaveBeenCalled();
  expect(onRemove).not.toHaveBeenCalled();
  fireEvent.click(within(list).getByRole('button', { name: 'Edit note for mark (removed words)' }));
  expect(onEdit).toHaveBeenCalledWith(mark);
  fireEvent.click(within(list).getByRole('button', { name: 'Remove mark (removed words)' }));
  expect(onRemove).toHaveBeenCalledWith(mark);
  fireEvent.click(play);
  expect(onPlay).toHaveBeenCalledWith(mark);
});
