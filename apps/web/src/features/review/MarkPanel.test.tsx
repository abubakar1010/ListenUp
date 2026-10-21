import { act, render } from '@testing-library/react';

import { STICKY_HEADER_CLEARANCE } from '../session/PracticeLayout';
import { MarkPanel } from './MarkPanel';

/** The panel's own clearance for the sticky header (#58, UI-4; WCAG 2.4.11). */

const IDLE = {
  selection: null,
  phrase: '',
  mark: undefined,
  wordCount: 3,
  status: { kind: 'saved', at: null } as const,
  announcement: '',
  focusNote: false,
  onSelect: () => {},
  onMark: () => {},
  onNote: () => {},
  onRemove: () => {},
  onNoteFocused: () => {},
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.documentElement.style.scrollPaddingTop = '';
});

test('when_only_the_panel_goes_the_page_keeps_the_headers_scroll_padding', async () => {
  vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(100);
  vi.stubGlobal(
    'ResizeObserver',
    class {
      constructor(private readonly callback: () => void) {}
      observe() {
        queueMicrotask(this.callback);
      }
      disconnect() {}
    },
  );
  const { unmount } = render(<MarkPanel {...IDLE} />);
  await act(async () => {});
  expect(document.documentElement.style.scrollPaddingTop).not.toBe(STICKY_HEADER_CLEARANCE);
  unmount();
  expect(document.documentElement.style.scrollPaddingTop).toBe(STICKY_HEADER_CLEARANCE);
});

test('a_panel_that_scrolls_with_the_page_leaves_the_scroll_padding_to_the_header', async () => {
  vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(300);
  const observe = vi.fn();
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe = observe;
      disconnect() {}
    },
  );
  const marked = {
    id: 'm1',
    word_from: 0,
    word_to: 0,
    at_ms: 1000,
    note: null,
    saved: true,
  };
  render(<MarkPanel {...IDLE} selection={{ anchor: 0, focus: 0 }} phrase="Hello" mark={marked} />);
  await act(async () => {});
  expect(observe).not.toHaveBeenCalled(); // only a sticky panel can cover a focused word
});
