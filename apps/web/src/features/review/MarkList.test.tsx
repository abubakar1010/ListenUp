import { fireEvent, render, screen, within } from '@testing-library/react';

import { MarkList } from './MarkList';
import type { LocalMark } from './markSync';

// Supplementary interaction coverage of the implemented list (#60, UI-4).
test('list_buttons_offer_edit_remove_and_ignore_modified_or_repeated_shortcuts', () => {
  const mark = {
    id: 'm1',
    word_from: 0,
    word_to: 0,
    at_ms: 0,
    note: null,
    tag: null,
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
      onTag={vi.fn()}
    />,
  );
  const list = screen.getByRole('list', { name: 'Your marks' });
  // Each name starts with or contains the words on the button (WCAG 2.5.3, #98); the
  // separator dot is visible only, so screen readers do not announce it.
  const play = within(list).getByRole('button', { name: 'Play mark 00:00 (removed words)' });
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

// -- tags (#61, FR-TR-4) -------------------------------------------------------------------

function listMark(values: Partial<LocalMark> = {}): LocalMark {
  return {
    id: 'm1',
    word_from: 0,
    word_to: 1,
    at_ms: 61_000,
    note: null,
    tag: null,
    source: 'manual',
    status: 'confirmed',
    saved: true,
    ...values,
  };
}

function renderList(marks: LocalMark[], onTag = vi.fn()) {
  render(
    <MarkList
      marks={marks}
      phraseOf={(mark) => (mark.id === 'm1' ? 'a lot' : 'of it')}
      onPlay={vi.fn()}
      onEdit={vi.fn()}
      onConfirm={vi.fn()}
      onRemove={vi.fn()}
      onTag={onTag}
    />,
  );
  return onTag;
}

test('each_mark_in_the_list_shows_its_tag_in_words', () => {
  renderList([listMark({ tag: 'weak_form' }), listMark({ id: 'm2', at_ms: 62_000 })]);
  const [first, second] = within(screen.getByRole('list', { name: 'Your marks' })).getAllByRole(
    'listitem',
  );
  expect(within(first!).getByText('Your mark · Weak form')).toBeInTheDocument();
  expect(within(second!).getByText('Your mark')).toBeInTheDocument();
  expect(within(second!).queryByText(/^Your mark ·/)).not.toBeInTheDocument();
});

test('the_tag_can_be_set_changed_and_cleared_from_the_list', () => {
  const onTag = renderList([listMark()]);
  const select = screen.getByRole('combobox', { name: 'Tag for mark a lot' });
  expect(select).toHaveValue('');
  expect(
    within(select)
      .getAllByRole('option')
      .map((option) => option.textContent),
  ).toEqual(['No tag', 'Linking', 'Reduction', 'Weak form', 'Unknown word']);
  fireEvent.change(select, { target: { value: 'linking' } });
  expect(onTag).toHaveBeenLastCalledWith(expect.objectContaining({ id: 'm1' }), 'linking');
  fireEvent.change(select, { target: { value: 'unknown_word' } });
  expect(onTag).toHaveBeenLastCalledWith(expect.objectContaining({ id: 'm1' }), 'unknown_word');
  fireEvent.change(select, { target: { value: '' } });
  expect(onTag).toHaveBeenLastCalledWith(expect.objectContaining({ id: 'm1' }), null);
});

test('the_list_select_shows_the_current_tag_as_its_state', () => {
  renderList([listMark({ tag: 'reduction' })]);
  const select = screen.getByRole('combobox', { name: 'Tag for mark a lot' });
  expect(select).toHaveValue('reduction');
  expect(within(select).getByRole('option', { name: 'Reduction' })).toHaveProperty(
    'selected',
    true,
  );
});
