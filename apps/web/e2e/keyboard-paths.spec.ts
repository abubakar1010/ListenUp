import type { Page } from '@playwright/test';

import { expect, isMacWebKit, requireRecording, SAFARI_SELECT, test } from './test';
import { expectFocusKept } from './focus';
import { activate, expectNoSideScroll, focusIndicator, playThrough, tabTo } from './keyboard/keys';
import { planServer, TYPED, type Entry, type PlanState } from './keyboard/planServer';

/*
 * AT-7, NFR-USE-2 (#98): a keyboard-only learner completes each plan path, from the
 * library to the finished plan, including marks, a card and the three Shadow rounds.
 * Every control is reached with Tab and used with Enter, Space, arrows or typing;
 * each Tab stop must show a focus indicator. Each path runs at 1280 px and at 360 px
 * (UI-4), where every screen is also checked for sideways scrolling.
 *
 * Against a mocked API (planServer.ts): this proves the browser side of the path.
 */

const PATHS: { entry: Entry; steps: number }[] = [
  { entry: 'blind', steps: 4 },
  { entry: 'dictation', steps: 4 },
  { entry: 'both', steps: 5 },
];
const WIDTHS = [1280, 360];

/**
 * Reported, not fixed here: `src/features/shadow` is being changed by #82. When a round's
 * playback ends, the focused round control is removed and focus falls to the page body
 * (WCAG 2.4.3). Tab from the body still reaches "Start round N" in Chromium. See
 * docs/validation/98-keyboard-and-statement.md.
 */
const SHADOW_ROUND_END =
  'Shadow: focus falls to the page when a round ends (#98 report; shadow files are #82)';

// The fake refuses a write without the CSRF header, as the API does, and the run fails on it.
test('the plan server refuses a write without the CSRF header', async ({ page }) => {
  const server = await planServer(page);
  await page.goto('/library');
  await expect(page.getByRole('heading', { level: 1, name: 'Library' })).toBeVisible();
  const status = await page.evaluate(async () => {
    const response = await fetch('/api/v1/sessions', { method: 'POST', body: '{}' });
    return response.status;
  });
  expect(status).toBe(403);
  expect(server.unanswered).toEqual(['POST /sessions without X-CSRF-Token']);
});

// WCAG 2.4.7: the check must not pass a resting shadow or an invisible outline.
test('the focus indicator check needs a visible outline or a focus-ring shadow', async ({
  page,
}) => {
  await page.setContent(`
    <style>:root { --color-focus-ring: rgb(10, 90, 200); }</style>
    <button id="ring" style="outline: 3px solid var(--color-focus-ring)">Ring</button>
    <button id="shadow" style="outline: none; box-shadow: 0 0 0 3px var(--color-focus-ring)">Shadow</button>
    <button id="resting" style="outline: none; box-shadow: 0 1px 2px rgb(0 0 0 / 0.3)">Resting</button>
    <button id="clear" style="outline: 2px solid transparent">Clear</button>
    <button id="thin" style="outline: 1px solid black">Thin</button>`);
  const visible = async (id: string) => {
    await page.locator(`#${id}`).focus();
    return (await focusIndicator(page)).visible;
  };
  expect(await visible('ring')).toBe(true);
  expect(await visible('shadow')).toBe(true);
  expect(await visible('resting')).toBe(false);
  expect(await visible('clear')).toBe(false);
  expect(await visible('thin')).toBe(false);
});

for (const { entry, steps } of PATHS) {
  for (const width of WIDTHS) {
    test(`keyboard only: the ${entry} path to the finished plan at ${width} px`, async ({
      page,
      browserName,
    }) => {
      // The Card's mark list is a native select, which Safari opens on ArrowDown.
      test.skip(isMacWebKit(browserName), SAFARI_SELECT);
      test.setTimeout(90_000);
      await page.setViewportSize({ width, height: 800 });
      const server = await planServer(page);

      await startPlan(page, entry, steps);
      await checkLayout(page, 'on the first step');
      if (entry !== 'dictation') await blind(page, server, entry === 'both' ? 'Dictation' : null);
      if (entry !== 'blind') await dictation(page, steps);
      await transcript(page, server, entry);
      await card(page, server);
      await shadow(page, server, browserName, steps);

      expect(server.voids, 'a Blind attempt was voided on the way').toEqual([]);
      expect(server.unanswered, 'requests the plan server does not answer').toEqual([]);
    });
  }
}

async function checkLayout(page: Page, where: string) {
  if (page.viewportSize()!.width <= 360) await expectNoSideScroll(page, where);
}

/** Library → Start a plan → entry choice → Start plan. */
async function startPlan(page: Page, entry: Entry, steps: number) {
  await page.goto('/library');
  await expect(page.getByRole('heading', { level: 1, name: 'Library' })).toBeVisible();
  await checkLayout(page, 'in the library');
  await activate(
    page,
    page.getByRole('link', { name: `Start a plan on Why cities plant street trees` }),
    'Enter',
    { loaded: true },
  );

  await expect(page.getByRole('heading', { level: 1, name: 'Start a plan' })).toBeVisible();
  await expect(page.getByRole('radio', { name: /Whole clip/ })).toBeChecked();
  await checkLayout(page, 'on Start a plan');
  const blindBox = page.getByRole('checkbox', { name: /^Blind/ });
  const dictationBox = page.getByRole('checkbox', { name: /^Dictation/ });
  if (entry !== 'blind') await activate(page, dictationBox, 'Space');
  if (entry === 'dictation') await activate(page, blindBox, 'Space', { back: true, max: 10 });
  await expect(blindBox).toBeChecked({ checked: entry !== 'dictation' });
  await expect(dictationBox).toBeChecked({ checked: entry !== 'blind' });
  await expect(page.getByText(`Your plan: ${steps} steps`)).toBeVisible();
  await activate(page, page.getByRole('button', { name: 'Start plan' }));

  await expect(page).toHaveURL('/sessions/s-1');
  await expect(page.getByText(`Step 1 of ${steps}`)).toBeVisible();
  // AT-7: the entry can change until Transcript starts.
  await expect(page.getByRole('button', { name: 'Change entry' })).toBeVisible();
}

/** Blind: Start listening, the whole passage, a three-sentence gist, Continue. */
async function blind(page: Page, server: PlanState, next: 'Dictation' | null) {
  const player = page.getByRole('group', { name: 'Blind player' });
  await activate(page, player.getByRole('button', { name: 'Start listening' }));
  await expect(player.getByText('Listening', { exact: true })).toBeVisible();
  await expect(player.getByTestId('blind-status')).toBeFocused();
  await playThrough(page.locator('audio'), server.passage.end_ms / 1000, { seek: false });

  const gist = page.getByRole('textbox', { name: 'Your gist' });
  await expect(gist).toBeFocused();
  await checkLayout(page, 'on the gist form');
  await page.keyboard.type(
    'Cities plant trees on streets. Shade cools the air. Roots can break pipes.',
  );
  await activate(page, page.getByRole('button', { name: 'Submit gist' }));
  // Grading runs in the background and never blocks the plan; its state is announced.
  await expect(page.getByText('Preparing your gist feedback…')).toBeVisible();
  await activate(page, page.getByRole('button', { name: `Continue to ${next ?? 'Transcript'}` }));
  await expect(
    page.getByRole('heading', { level: 1, name: new RegExp(next ?? 'Transcript') }),
  ).toBeVisible();
}

/** Dictation: play by keyboard, type, submit, confirm. */
async function dictation(page: Page, steps: number) {
  const text = page.getByRole('textbox', { name: 'Your text' });
  // UX-42: arrival at Dictation puts focus on the text box, not the h1.
  await expect(text).toBeFocused();
  await checkLayout(page, 'on Dictation');
  const player = page.getByRole('region', { name: 'Player' });
  const play = player.getByRole('button', { name: 'Play', exact: true });
  await expect(play).toBeEnabled();
  await activate(page, play);
  await expect(player.getByRole('button', { name: 'Pause' })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(play).toBeFocused();

  await tabTo(page, text);
  await page.keyboard.type(TYPED);
  await activate(page, page.getByRole('button', { name: 'Submit for scoring' }));
  const dialog = page.getByRole('dialog', { name: 'Submit your Dictation?' });
  await expect(dialog.getByRole('button', { name: 'Keep typing' })).toBeFocused();
  await activate(page, dialog.getByRole('button', { name: 'Submit', exact: true }), 'Enter', {
    max: 3,
  });
  await expect(page.getByText(`Step ${steps - 2} of ${steps}`)).toBeVisible();
}

/**
 * Transcript: after Dictation, add the missed word from the diff and confirm it in the
 * marks list; after Blind only, select two words with Shift+arrow and press M.
 */
async function transcript(page: Page, server: PlanState, entry: Entry) {
  await expect(page.getByRole('button', { name: 'Jump to plant' })).toBeVisible();
  await expect(page.getByRole('heading', { level: 1, name: /^Transcript:/ })).toBeFocused();
  // AT-7: and not after.
  await expect(page.getByText('Entry locked')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Change entry' })).toHaveCount(0);
  await checkLayout(page, 'on Transcript');
  const list = page.getByRole('list', { name: 'Your marks' });
  if (entry === 'blind') {
    const shade = page.getByRole('button', { name: 'Jump to Shade' });
    await tabTo(page, shade, { max: 60 });
    await page.keyboard.press('Shift+ArrowRight');
    await page.keyboard.press('m');
    await expect(shade).toHaveAccessibleDescription('Marked');
    await expect(page.getByRole('region', { name: 'Mark words' })).toContainText('Marks saved');
    await expect(list.getByRole('listitem')).toHaveCount(1);
  } else {
    await activate(page, page.getByRole('button', { name: 'Add “plant” to marks' }), 'Enter', {
      max: 80,
    });
    await expect(page.getByRole('button', { name: '“plant” added to marks' })).toBeVisible();
    await activate(page, list.getByRole('button', { name: 'Confirm mark plant' }), 'Enter', {
      max: 80,
    });
    await expect(list).not.toContainText('To confirm');
    await expect.poll(() => server.marks.map((m) => m.status)).toEqual(['confirmed']);
  }
  await checkLayout(page, 'with a mark');
  await activate(
    page,
    page.getByRole('button', { name: 'Finish Transcript', exact: true }),
    'Enter',
    { max: 80 },
  );
  await expect(page.getByRole('combobox', { name: 'Marked phrase' })).toBeVisible();
}

/** Card: choose the mark, write the heard form, save, finish. */
async function card(page: Page, server: PlanState) {
  await checkLayout(page, 'on Card');
  const phrase = page.getByRole('combobox', { name: 'Marked phrase' });
  await expect(phrase.getByRole('option', { name: /·/ })).toHaveCount(1);
  await tabTo(page, phrase, { max: 60 });
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('Tab');
  const written = page.getByRole('textbox', { name: 'Written form' });
  await expect(written).toBeFocused();
  await expect(written).not.toHaveValue('');
  await activate(page, page.getByRole('textbox', { name: 'Heard form' }), 'End', { max: 3 });
  await page.keyboard.type('shay coolz');
  await activate(page, page.getByRole('button', { name: 'Save card' }), 'Enter', { max: 3 });
  await expect(page.getByText('1 left', { exact: true }).first()).toBeVisible();
  expect(server.cards).toHaveLength(1);
  await checkLayout(page, 'with a card');
  await activate(page, page.getByRole('button', { name: 'Finish Card' }), 'Enter', { max: 30 });
}

/** Shadow: microphone check, voice consent, then three rounds; the third finishes the plan. */
async function shadow(page: Page, server: PlanState, browserName: string, steps: number) {
  const check = page.getByRole('button', { name: 'Check microphone' });
  await expect(check).toBeVisible();
  await requireRecording(page, browserName, false);
  await checkLayout(page, 'on Shadow');
  await activate(page, check, 'Enter', { max: 60 });
  await expect(page.getByText('Microphone ready. Sound detected.')).toBeVisible();
  await activate(page, page.getByRole('checkbox', { name: /I agree/ }), 'Space');
  await activate(page, page.getByRole('button', { name: 'Agree to voice recording' }), 'Enter', {
    max: 3,
  });
  await expect(page.getByText(/You agreed to this version/)).toBeFocused();

  for (const number of [1, 2, 3]) {
    await activate(
      page,
      page.getByRole('button', { name: `Start round ${number}`, exact: true }),
      'Enter',
      { max: 60, knownFocusLoss: number > 1 ? SHADOW_ROUND_END : undefined },
    );
    await expect(page.getByRole('heading', { name: `Round ${number} of 3` })).toBeFocused();
    const play = page.getByRole('button', { name: `Play round ${number}`, exact: true });
    await expect(play).toBeEnabled();
    await activate(page, play, 'Space', { max: 30 });
    await expect(
      page.getByRole('status').filter({ hasText: 'playing at original speed' }),
    ).toBeVisible();
    await checkLayout(page, `in round ${number}`);
    await playThrough(page.locator('audio:not([controls])'), server.passage.end_ms / 1000 + 0.1);
    if (number < 3)
      await expect(page.getByRole('list', { name: 'Round status' })).toContainText(
        `Round ${number}: recorded`,
      );
  }
  await expect(page.getByText(`All ${steps} steps finished`)).toBeVisible();
  await expectFocusKept(page, 'on the finished plan');
  expect(server.uploads).toEqual([1, 2, 3]);
  await checkLayout(page, 'on the finished plan');
}
