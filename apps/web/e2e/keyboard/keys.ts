import type { Locator, Page } from '@playwright/test';

import { expect, test } from '../test';

/*
 * Keyboard-only helpers for the plan-path specs (#98, AT-7, NFR-USE-2). A control is
 * reached by pressing Tab from wherever focus is, never by `focus()` or a click, so a
 * control missing from the Tab order fails the spec.
 */

/**
 * What the focused element shows for WCAG 2.4.7: an outline at least 2 px wide in a colour
 * that draws, or a box-shadow ring in the focus-ring colour.
 */
export async function focusIndicator(page: Page) {
  return page.evaluate(() => {
    const element = document.activeElement as HTMLElement | null;
    if (!element || element === document.body) return { lost: true, name: '', visible: false };
    // Native media controls draw the browser's own ring on their inner buttons, which
    // are out of reach of getComputedStyle; the manual checklist covers them.
    const native = element.matches('audio[controls], video[controls]');
    const style = getComputedStyle(element);
    // A colour with no alpha, or alpha 0, draws nothing.
    const drawn = (color: string) => !/^transparent$|rgba\([^)]*,\s*0\)$/.test(color.trim());
    const outline =
      style.outlineStyle !== 'none' &&
      parseFloat(style.outlineWidth) >= 2 &&
      drawn(style.outlineColor);
    // A box-shadow counts only when it draws in the focus-ring colour: a resting shadow
    // is not a focus indicator.
    const tokenSet =
      getComputedStyle(document.documentElement).getPropertyValue('--color-focus-ring') !== '';
    const probe = document.createElement('span');
    probe.style.color = 'var(--color-focus-ring)';
    document.body.append(probe);
    const focusRing = getComputedStyle(probe).color;
    probe.remove();
    const ring = tokenSet && style.boxShadow !== 'none' && style.boxShadow.includes(focusRing);
    const name =
      element.getAttribute('aria-label') ??
      ((element.textContent ?? '').trim().slice(0, 40) || element.tagName);
    return {
      lost: false,
      name: `${element.tagName.toLowerCase()} "${name}"`,
      visible: native || outline || ring,
    };
  });
}

interface TabOptions {
  max?: number;
  /** Shift+Tab instead of Tab. */
  back?: boolean;
  /** The page was just loaded, so focus starts on the body. */
  loaded?: boolean;
  /**
   * A reported focus loss in code this spec may not change: recorded as an annotation
   * instead of failing. Once focus is kept, the spec fails so the exemption is removed.
   */
  knownFocusLoss?: string;
}

/**
 * Press Tab (or Shift+Tab) until `target` has focus. Fails when the previous action left
 * focus on the page body (WCAG 2.4.3, as in `expectFocusKept`), when a stop on the way
 * shows no focus indicator (2.4.7), or when `target` is not reached within `max` presses.
 * Tab past the last control leaves the page and comes back at the first, as browsers do;
 * that happens at most once.
 */
export async function tabTo(
  page: Page,
  target: Locator,
  { max = 40, back = false, loaded = false, knownFocusLoss }: TabOptions = {},
) {
  const key = back ? 'Shift+Tab' : 'Tab';
  const start = await focusIndicator(page);
  if (knownFocusLoss) {
    expect(start.lost, `focus is kept now; remove the exemption "${knownFocusLoss}"`).toBe(true);
    test.info().annotations.push({ type: 'known-focus-loss', description: knownFocusLoss });
  } else if (!loaded)
    expect(start.lost, `focus was on the page body before reaching ${String(target)}`).toBe(false);
  let wrapped = false;
  for (let presses = 0; presses < max; presses++) {
    if (await target.evaluate((el) => el === document.activeElement).catch(() => false)) return;
    await page.keyboard.press(key);
    const focus = await focusIndicator(page);
    if (focus.lost) {
      expect(wrapped, `${String(target)} is not in the Tab order`).toBe(false);
      wrapped = true;
      continue;
    }
    expect(focus.visible, `no visible focus indicator on ${focus.name}`).toBe(true);
  }
  await expect(target, `not reached with ${max} presses of ${key}`).toBeFocused();
}

/** Reach `target` by Tab and press `key` on it (Enter for buttons and links). */
export async function activate(
  page: Page,
  target: Locator,
  key = 'Enter',
  options: TabOptions = {},
) {
  await tabTo(page, target, options);
  await page.keyboard.press(key);
}

/** UI-4: the page never scrolls sideways at the current width. */
export async function expectNoSideScroll(page: Page, where: string) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow, `horizontal overflow ${where}`).toBeLessThanOrEqual(0);
}

/**
 * The media element reaches `seconds` and reports it, the way playing to the end does.
 * The learner presses no key for this; it stands in for waiting. Blind voids an attempt
 * on a seek, so there the clock is read differently instead of moving the playhead.
 */
export async function playThrough(audio: Locator, seconds: number, { seek = true } = {}) {
  await audio.evaluate(
    (element: HTMLAudioElement, [at, move]) => {
      if (move) element.currentTime = at;
      else Object.defineProperty(element, 'currentTime', { configurable: true, get: () => at });
      element.dispatchEvent(new Event('timeupdate'));
    },
    [seconds, seek] as const,
  );
}
