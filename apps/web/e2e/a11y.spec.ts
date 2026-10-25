import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

import { ALLOWED, allowlistProblems } from './a11y/allowlist';
import { fakeApi } from './a11y/fakeApi';
import { STATES } from './a11y/states';

/*
 * axe on every route and main state (#98, NFR-USE-2, UI-4), run by the a11y-* projects
 * at 1280 px, at 360 px and in the dark theme. Serious and critical WCAG 2.1 A/AA
 * violations fail; the rest are attached to the report.
 */

const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'];
const BLOCKING = new Set(['serious', 'critical']);

test('every allowlist entry has a reason, an issue and an owned scan state', () => {
  const owners = new Map(STATES.map((state) => [state.name, state.owner]));
  expect(allowlistProblems(ALLOWED, owners)).toEqual([]);
});

test('scan state names are unique', () => {
  const names = STATES.map((state) => state.name);
  expect(names.filter((name, i) => names.indexOf(name) !== i)).toEqual([]);
});

for (const state of STATES) {
  test(`axe: ${state.name}`, async ({ page }, testInfo) => {
    const narrow = (page.viewportSize()?.width ?? 1280) <= 400;
    test.skip(state.only === 'narrow' && !narrow, 'only exists at narrow widths');

    await fakeApi(page, state.answers ?? {}, state.signedIn ?? false);
    await page.goto(state.path);
    await state.act?.(page);
    await expect(state.ready(page)).toBeVisible();
    await page.evaluate(() => document.fonts.ready);

    const results = await new AxeBuilder({ page }).withTags(TAGS).analyze();
    await testInfo.attach('axe-results.json', {
      body: JSON.stringify({ url: page.url(), violations: results.violations }, null, 2),
      contentType: 'application/json',
    });

    const allowed = ALLOWED.filter((entry) => entry.state === state.name);
    const blocking = results.violations.filter((violation) => BLOCKING.has(violation.impact ?? ''));
    const unexpected = blocking
      .filter((violation) => !allowed.some((entry) => entry.rule === violation.id))
      .map(
        (violation) =>
          `${violation.id} (${violation.impact}): ${violation.help} → ` +
          violation.nodes.map((node) => node.target.join(' ')).join(', '),
      );
    expect(unexpected, `serious or critical axe violations on ${page.url()}`).toEqual([]);
    const stale = allowed
      .filter((entry) => !blocking.some((violation) => violation.id === entry.rule))
      .map((entry) => `${entry.rule}: no longer found, remove it (${entry.issue})`);
    expect(stale, 'allowlist entries that no longer match').toEqual([]);

    if (narrow) {
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, 'sideways scrolling at 360 px (UI-4)').toBeLessThanOrEqual(0);
    }
  });
}
