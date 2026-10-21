import { act, render } from '@testing-library/react';

import { STICKY_HEADER_CLEARANCE } from '../session/PracticeLayout';
import { MarkPanel } from './MarkPanel';

/** The panel's own clearance for the sticky header (#58, UI-4; WCAG 2.4.11). */

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
  const idle = {
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
  const { unmount } = render(<MarkPanel {...idle} />);
  await act(async () => {});
  expect(document.documentElement.style.scrollPaddingTop).not.toBe(STICKY_HEADER_CLEARANCE);
  unmount();
  expect(document.documentElement.style.scrollPaddingTop).toBe(STICKY_HEADER_CLEARANCE);
});
