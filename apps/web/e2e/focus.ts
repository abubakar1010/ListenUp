import { expect, type Page } from '@playwright/test';

/**
 * Fails when keyboard focus has fallen to the page body, which happens in Chromium
 * when the focused control is disabled or removed (WCAG 2.4.3, #195).
 */
export async function expectFocusKept(page: Page, where: string) {
  const lost = await page.evaluate(
    () => document.activeElement === null || document.activeElement === document.body,
  );
  expect(lost, `focus fell to the page body ${where}`).toBe(false);
}
