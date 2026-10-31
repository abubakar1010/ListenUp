import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

import {
  ALLOWED,
  ISSUE,
  allowedFor,
  allowlistProblems,
  ownerProblems,
  type AllowedViolation,
} from './a11y/allowlist';
import { fakeApi } from './a11y/fakeApi';
import { STATES } from './a11y/states';
import { compareTargets, KNOWN_SMALL_TARGETS, smallTargets } from './a11y/targets';

/*
 * axe on every route and main state (#98, NFR-USE-2, UI-4), run by the a11y-* projects
 * at 1280 px, at 360 px and in the dark theme. Serious and critical WCAG 2.1 A/AA
 * violations fail; the rest, and what axe could not decide, are attached to the report.
 * Each state must also be the screen it names: no unanswered request and no alert
 * unless the state is about one.
 */

const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'];
const BLOCKING = new Set(['serious', 'critical']);

test('every allowlist entry has a reason, an issue and an owned scan state', () => {
  const owners = new Map(STATES.map((state) => [state.name, state.owner]));
  expect(allowlistProblems(ALLOWED, owners)).toEqual([]);
});

test('only screens owned by #70, #73 or #79 may hold exceptions', () => {
  expect(ownerProblems(STATES)).toEqual([]);
  expect(ownerProblems([{ name: 'library empty', owner: `${ISSUE}/98` }])).toEqual([
    `"library empty" is owned by ${ISSUE}/98, which may not hold exceptions`,
  ]);
});

test('allowlist problems name each broken rule', () => {
  const owners = new Map([
    ['card', `${ISSUE}/73`],
    ['sign-in', undefined],
    ['other', `${ISSUE}/98`],
  ]);
  const entry = (overrides: Partial<AllowedViolation>): AllowedViolation => ({
    rule: 'color-contrast',
    state: 'card',
    reason: 'The Card redesign replaces this badge.',
    issue: `${ISSUE}/73`,
    ...overrides,
  });
  expect(allowlistProblems([entry({ projects: ['a11y-dark'] })], owners)).toEqual([]);
  expect(
    allowlistProblems(
      [
        entry({ reason: ' ' }),
        entry({ issue: 'see #73' }),
        entry({ state: 'sign-in' }),
        entry({ state: 'gone' }),
        entry({ state: 'other', issue: `${ISSUE}/98` }),
        entry({ projects: [] }),
        entry({ projects: ['chromium'] }),
      ],
      owners,
    ),
  ).toEqual([
    'color-contrast on "card" has no reason',
    'color-contrast on "card" does not link a GitHub issue',
    'color-contrast on "card" is not on a screen owned by see #73',
    `color-contrast on "sign-in" is not on a screen owned by ${ISSUE}/73`,
    'color-contrast on "gone" names no scan state',
    `color-contrast on "other" links ${ISSUE}/98, which may not hold exceptions`,
    'color-contrast on "card" lists no project',
    'color-contrast on "card" names unknown project chromium',
  ]);
  const dark = entry({ projects: ['a11y-dark'] });
  expect(allowedFor([dark], 'card', 'a11y-dark')).toEqual([dark]);
  expect(allowedFor([dark], 'card', 'a11y-360')).toEqual([]);
  expect(allowedFor([entry({})], 'card', 'a11y-360')).toHaveLength(1);
});

test('known small targets name scan states and a reason, and are compared by prefix', () => {
  const names = new Set(STATES.map((state) => state.name));
  for (const entry of KNOWN_SMALL_TARGETS) {
    expect(entry.reason.trim()).not.toBe('');
    expect(entry.states.filter((state) => !names.has(state))).toEqual([]);
  }
  const known = [{ states: ['a'], target: 'a "Link"', reason: 'r' }];
  expect(compareTargets('a', ['a "Link" 90×24', 'button "B" 30×30'], known)).toEqual({
    unexpected: ['button "B" 30×30'],
    stale: [],
  });
  expect(compareTargets('a', [], known).stale).toEqual([
    'a "Link": no longer found on "a", remove it',
  ]);
  expect(compareTargets('b', ['a "Link" 90×24'], known).unexpected).toEqual(['a "Link" 90×24']);
});

test('scan state names are unique', () => {
  const names = STATES.map((state) => state.name);
  expect(names.filter((name, i) => names.indexOf(name) !== i)).toEqual([]);
});

for (const state of STATES) {
  test(`axe: ${state.name}`, async ({ page }, testInfo) => {
    const narrow = (page.viewportSize()?.width ?? 1280) <= 400;
    test.skip(state.only === 'narrow' && !narrow, 'only exists at narrow widths');

    const unanswered = await fakeApi(page, state.answers ?? {}, state.signedIn ?? false);
    await page.goto(state.path);
    await state.act?.(page);
    await expect(state.ready(page)).toBeVisible();
    await page.evaluate(() => document.fonts.ready);

    // A state that lands on a "not found" card or an error message scans the wrong screen.
    expect(unanswered, `requests "${state.name}" does not answer`).toEqual([]);
    if (!state.alert) {
      const alerts = (await page.getByRole('alert').allInnerTexts())
        .map((text) => text.trim())
        .filter(Boolean);
      expect(alerts, `alerts on "${state.name}", which expects none`).toEqual([]);
    }

    const results = await new AxeBuilder({ page }).withTags(TAGS).analyze();
    await testInfo.attach('axe-results.json', {
      body: JSON.stringify(
        { url: page.url(), violations: results.violations, incomplete: results.incomplete },
        null,
        2,
      ),
      contentType: 'application/json',
    });

    const allowed = allowedFor(ALLOWED, state.name, testInfo.project.name);
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
      const { unexpected: small, stale: fixed } = compareTargets(
        state.name,
        await smallTargets(page),
      );
      expect(small, 'targets under 44 px at 360 px (UX-15, WCAG 2.5.8)').toEqual([]);
      expect(fixed, 'known small targets that are fixed now').toEqual([]);
    }
  });
}
