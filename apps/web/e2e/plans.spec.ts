import { expect, test } from './test';
import { expectFocusKept } from './focus';
import { fakeApi } from './plan-api';

test('a learner starts a plan from the library and sees step 1 of 5', async ({ page }) => {
  const { posts } = await fakeApi(page);
  await page.goto('/library');

  await page.getByRole('link', { name: 'Start a plan on Why cities plant street trees' }).click();
  await expect(page).toHaveURL('/contents/clip-1/plan');
  await expect(page.getByRole('heading', { name: 'Start a plan', level: 1 })).toBeVisible();

  // 12:40 is under 15 minutes, so the whole clip is chosen; Blind is ticked.
  await expect(page.getByRole('radio', { name: /Whole clip/ })).toBeChecked();
  await expect(page.getByText('Your plan: 4 steps')).toBeVisible();
  await page.getByRole('checkbox', { name: /Dictation/ }).check();
  await expect(page.getByText('Your plan: 5 steps')).toBeVisible();

  await page.getByRole('button', { name: 'Start plan' }).click();

  await expect(page).toHaveURL('/sessions/s-1');
  await expect(page.getByText('Step 1 of 5')).toBeVisible();
  const steps = page.getByRole('list', { name: 'Plan steps' }).getByRole('listitem');
  await expect(steps).toHaveCount(5);
  await expect(steps.first()).toHaveAttribute('aria-current', 'step');
  expect(posts).toHaveLength(1);
  expect(posts[0].body).toEqual({
    content_id: 'clip-1',
    passage: { start_ms: 0, end_ms: 760_000 },
    entry: 'both',
  });
  expect(posts[0].key).toBeTruthy();

  // Back in the library, the plan is listed with where it stands.
  await page.goto('/library');
  const plans = page.getByRole('region', { name: 'Your plans' });
  await expect(plans).toContainText('Step 1 of 5 · Blind');
  await plans.getByRole('link', { name: /Resume/ }).click();
  await expect(page).toHaveURL('/sessions/s-1');
});

test('a part of the clip is typed at 360 px', async ({ page }) => {
  const { posts } = await fakeApi(page);
  await page.setViewportSize({ width: 360, height: 740 });
  await page.goto('/contents/clip-1/plan');

  await page.getByRole('radio', { name: /A part of it/ }).check();
  await page.getByRole('textbox', { name: 'Start' }).fill('02:10');
  await page.getByRole('textbox', { name: 'Start' }).press('Tab');
  await page.getByRole('textbox', { name: 'End' }).fill('02:20');
  // Enter submits; the end is first set to 30 s after the start, so the plan waits.
  await page.getByRole('textbox', { name: 'End' }).press('Enter');
  await expect(page.getByRole('textbox', { name: 'End' })).toHaveValue('02:40');
  await expect(page.getByRole('textbox', { name: 'End' })).toBeFocused();
  expect(posts).toHaveLength(0);

  await page.getByRole('textbox', { name: 'End' }).fill('04:40');
  // The plan starts slowly: Start plan keeps focus and says it is busy (#195).
  let answer: () => void = () => undefined;
  const answered = new Promise<void>((resolve) => (answer = resolve));
  await page.route('**/api/v1/sessions', async (route) => {
    if (route.request().method() === 'POST') await answered;
    await route.fallback();
  });
  await page.getByRole('button', { name: 'Start plan' }).focus();
  await page.keyboard.press('Enter');
  const starting = page.getByRole('button', { name: 'Starting…' });
  await expect(starting).toHaveAttribute('aria-busy', 'true');
  await expect(starting).toBeFocused();
  await page.keyboard.press('Enter'); // a second press sends nothing
  await expectFocusKept(page, 'while the plan starts');
  answer();
  await expect(page).toHaveURL('/sessions/s-1');
  await expect(page.getByText('Step 1 of 4')).toBeVisible();
  expect(posts).toHaveLength(1);
  expect(posts[0].body).toMatchObject({ passage: { start_ms: 130_000, end_ms: 280_000 } });

  // The step names do not fit at 360 px: Plan opens the full list as a sheet (UX-09).
  const plan = page.getByRole('button', { name: 'Plan', exact: true });
  await plan.focus();
  await page.keyboard.press('Enter');
  const sheet = page.getByRole('dialog', { name: 'Your plan' });
  await expect(sheet.getByRole('listitem')).toHaveText([
    '1. Blind Now',
    '2. Transcript Locked',
    '3. Card Locked',
    '4. Shadow Locked',
  ]);
  const box = (await sheet.boundingBox())!;
  expect(box.y + box.height).toBeCloseTo(740, 0); // a bottom sheet
  await page.keyboard.press('Escape');
  await expect(sheet).toHaveCount(0);
  await expect(plan).toBeFocused();

  for (const path of ['/contents/clip-1/plan', '/sessions/s-1', '/library']) {
    await page.goto(path);
    await expect(page.getByRole('main')).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, `horizontal overflow on ${path}`).toBeLessThanOrEqual(0);
  }
});

test('before Transcript, adding Dictation makes the plan 5 steps', async ({ page }) => {
  await fakeApi(page, [
    {
      id: 's-1',
      entry: 'blind',
      passage: { start_ms: 0, end_ms: 150_000 },
      version: 0,
      statuses: { blind: 'open' },
    },
  ]);
  await page.goto('/sessions/s-1');

  await expect(page.getByText('Step 1 of 4')).toBeVisible();
  await page.getByRole('button', { name: 'Change entry' }).click();
  const panel = page.getByRole('region', { name: 'Change how you start' });
  await panel.getByRole('checkbox', { name: /Dictation/ }).check();
  await expect(panel.getByText('Your plan becomes: 5 steps')).toBeVisible();
  await panel.getByRole('button', { name: 'Save change' }).click();

  await expect(page.getByText('Step 1 of 5')).toBeVisible();
  await expect(page.getByRole('list', { name: 'Plan steps' }).getByRole('listitem')).toHaveCount(5);
  await expect(page.getByRole('button', { name: 'Change entry' })).toBeFocused();
});

test('Card and Shadow are skipped only after confirming, which completes the plan', async ({
  page,
}) => {
  await fakeApi(page, [
    {
      id: 's-1',
      entry: 'dictation',
      passage: { start_ms: 0, end_ms: 150_000 },
      version: 2,
      statuses: { dictation: 'done', transcript: 'done', card: 'open' },
    },
  ]);
  await page.setViewportSize({ width: 360, height: 740 });
  await page.goto('/sessions/s-1');

  await expect(page.getByText('Step 3 of 4')).toBeVisible();
  await expect(page.getByText('Entry locked')).toBeVisible();
  const skipCard = page.getByRole('button', { name: 'Skip Card' });
  await skipCard.focus();
  await page.keyboard.press('Enter');

  const dialog = page.getByRole('dialog', { name: 'Skip Card?' });
  await expect(dialog.getByRole('button', { name: 'Make a card' })).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(dialog.getByRole('button', { name: 'Skip Card' })).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(dialog.getByRole('button', { name: 'Make a card' })).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  await expect(skipCard).toBeFocused();
  await expect(page.getByText('Step 3 of 4')).toBeVisible();

  await skipCard.click();
  await dialog.getByRole('button', { name: 'Skip Card' }).click();
  await expect(page.getByText('Step 4 of 4')).toBeVisible();

  await page.getByRole('button', { name: 'Skip Shadow' }).click();
  await page.getByRole('button', { name: 'Skip Shadow and finish' }).click();
  await expect(page.getByText('All 4 steps finished')).toBeVisible();
  await expect(page.getByText('Skipped: Card and Shadow.')).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
});
