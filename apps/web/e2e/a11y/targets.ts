import type { Page } from '@playwright/test';

/** UX-15: touch layouts give every target at least 44 × 44 CSS px. */
export const TOUCH_TARGET_PX = 44;

/**
 * Visible controls whose hit area is under 44 px in either direction at a touch width
 * (UX-15, WCAG 2.5.8 at the stricter design size). The hit area is the control's box,
 * or for a checkbox or radio the label that wraps or names it. Exempt: transcript
 * words, which UX-15 gives the inline-target exception with their 32 px line (they carry
 * `data-inline-target`), and links inside running text (WCAG 2.5.8's inline exception;
 * UX-15 does not name these, an owner question on #260). A control inside a native media
 * element's own controls is the browser's and is not listed.
 */
export async function smallTargets(page: Page): Promise<string[]> {
  return page.evaluate((min) => {
    const selector = [
      'a[href]',
      'button',
      'input:not([type="hidden"])',
      'select',
      'textarea',
      'summary',
      '[role="slider"]',
      '[role="button"]',
      '[tabindex="0"]',
    ].join(',');
    const describe = (element: Element) => {
      const name =
        element.getAttribute('aria-label') ??
        (element.textContent ?? '').trim().replace(/\s+/g, ' ').slice(0, 40);
      return `${element.tagName.toLowerCase()} "${name}"`;
    };
    const inlineLink = (element: Element) =>
      element.tagName === 'A' && getComputedStyle(element).display === 'inline';
    const hitArea = (element: HTMLElement) => {
      const input = element as HTMLInputElement;
      if (element.tagName === 'INPUT' && ['checkbox', 'radio'].includes(input.type)) {
        const label = element.closest('label') ?? input.labels?.[0];
        if (label) return label.getBoundingClientRect();
      }
      const box = element.getBoundingClientRect();
      // A wider hit area drawn by an absolutely placed ::before (UX-15: "32 px look with a
      // 44 px hit area") counts, by how far its insets reach outside the box.
      const before = getComputedStyle(element, '::before');
      if (before.content === 'none' || before.position !== 'absolute') return box;
      const out = (value: string) => Math.max(0, -parseFloat(value) || 0);
      return {
        width: box.width + out(before.left) + out(before.right),
        height: box.height + out(before.top) + out(before.bottom),
      };
    };
    const small: string[] = [];
    for (const element of document.querySelectorAll<HTMLElement>(selector)) {
      if (element.closest('[aria-hidden="true"], [inert]')) continue;
      const box = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      if (box.width === 0 || box.height === 0 || style.visibility === 'hidden') continue;
      if (element.classList.contains('sr-only')) continue;
      if (inlineLink(element) || element.dataset.inlineTarget !== undefined) continue;
      const area = hitArea(element);
      if (area.width < min - 0.5 || area.height < min - 0.5)
        small.push(`${describe(element)} ${Math.round(area.width)}×${Math.round(area.height)}`);
    }
    return small;
  }, TOUCH_TARGET_PX);
}

export interface KnownSmallTarget {
  /** Scan states it appears on. */
  states: string[];
  /** The start of the entry `smallTargets` reports, for example `a "Voice recording consent"`. */
  target: string;
  reason: string;
}

/**
 * Small targets in code this story may not change, reported for the story that owns it.
 * The scan fails when one is no longer found, so the list only shrinks.
 */
export const KNOWN_SMALL_TARGETS: KnownSmallTarget[] = [
  {
    states: [
      'shadow segment',
      'shadow microphone denied',
      'shadow voice consent accepted',
      'shadow consent read failed',
    ],
    target: 'a "Voice recording consent"',
    reason:
      'ShadowReadiness.tsx (#82 is changing src/features/shadow): the consent link is a ' +
      '24 px block link; it needs min-h-11 (reported in docs/validation/98-keyboard-and-statement.md).',
  },
];

/** Splits what the scan found into unexpected targets and known entries no longer found. */
export function compareTargets(state: string, found: string[], known = KNOWN_SMALL_TARGETS) {
  const mine = known.filter((entry) => entry.states.includes(state));
  return {
    unexpected: found.filter((item) => !mine.some((entry) => item.startsWith(entry.target))),
    stale: mine
      .filter((entry) => !found.some((item) => item.startsWith(entry.target)))
      .map((entry) => `${entry.target}: no longer found on "${state}", remove it`),
  };
}
