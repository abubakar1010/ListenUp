import { expect, test, type Page, type Route } from '@playwright/test';

const LEARNER = {
  id: '1',
  email: 'learner@example.com',
  display_name: null,
  email_verified: false,
};
const UNTIL = '2026-10-11T20:30:00Z';

function problem(route: Route, status: number, code: string, detail: string, extra = {}) {
  return route.fulfill({
    status,
    contentType: 'application/problem+json',
    json: { type: `/problems/${code}`, title: '', status, detail, code, ...extra },
  });
}

/**
 * The account API in the browser (#91, #120): signed in until DELETE /me succeeds;
 * after that, sign-in answers account_pending_deletion until it is sent with
 * restore: true.
 */
async function fakeAccountApi(page: Page) {
  const state = { signedIn: true, deleted: false, deletes: [] as unknown[] };
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace('/api/v1', '');
    const method = request.method();
    if (path === '/health') {
      return route.fulfill({
        json: { status: 'ok' },
        headers: { 'Set-Cookie': 'listenup_csrf=e2e-token; Path=/; SameSite=Lax' },
      });
    }
    if (path === '/me' && method === 'DELETE') {
      const body = request.postDataJSON() as { password: string };
      state.deletes.push(body);
      if (body.password !== 'correct horse') {
        return problem(route, 403, 'wrong_password', 'The password is wrong.');
      }
      state.signedIn = false;
      state.deleted = true;
      return route.fulfill({
        status: 202,
        json: { deletion_scheduled_at: UNTIL, detail: 'Your account is deleted.' },
      });
    }
    if (path === '/auth/login') {
      const body = request.postDataJSON() as { restore?: boolean };
      if (state.deleted && !body.restore) {
        return problem(route, 409, 'account_pending_deletion', 'This account was deleted.', {
          deletion_scheduled_at: UNTIL,
        });
      }
      state.deleted = false;
      state.signedIn = true;
      return route.fulfill({ json: LEARNER });
    }
    if (!state.signedIn) return problem(route, 401, 'not_signed_in', 'Sign in to continue.');
    if (path === '/me') return route.fulfill({ json: LEARNER });
    if (path === '/library/contents' || path === '/sessions') {
      return route.fulfill({ json: { items: [], next_cursor: null } });
    }
    return problem(route, 404, 'not_found', path);
  });
  return state;
}

test('a learner deletes their account and restores it by signing in', async ({ page }) => {
  const state = await fakeAccountApi(page);

  await page.goto('/library');
  await page.getByRole('button', { name: 'Account' }).click();
  await page.getByRole('link', { name: 'Settings' }).click();
  await expect(page).toHaveTitle('Settings · ListenUp');

  // A wrong password closes the dialog and marks the field.
  await page.getByLabel('Your password').fill('not it');
  await page.getByRole('button', { name: 'Delete my account' }).click();
  let dialog = page.getByRole('dialog', { name: 'Delete your account?' });
  await expect(dialog.getByRole('button', { name: 'Keep my account' })).toBeFocused();
  await dialog.getByRole('button', { name: 'Delete my account' }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByLabel('Your password')).toHaveAttribute('aria-invalid', 'true');
  await expect(page.getByLabel('Your password')).toBeFocused();

  await page.getByLabel('Your password').fill('correct horse');
  await page.getByRole('button', { name: 'Delete my account' }).click();
  dialog = page.getByRole('dialog', { name: 'Delete your account?' });
  await dialog.getByRole('button', { name: 'Delete my account' }).click();

  await expect(page).toHaveURL(/\/account-deleted\?until=/);
  await expect(page.getByRole('heading', { name: 'Your account is deleted' })).toBeVisible();
  expect(state.deletes).toEqual([
    { password: 'not it', confirm: true },
    { password: 'correct horse', confirm: true },
  ]);

  // Signed out: the library sends the learner to sign in.
  await page.goto('/library');
  await expect(page).toHaveURL('/sign-in?next=%2Flibrary');
  await page.getByLabel('Email').fill('learner@example.com');
  await page.getByLabel('Password').fill('correct horse');
  await page.getByLabel('Password').press('Enter');

  const restore = page.getByRole('dialog', { name: 'Restore your account?' });
  await expect(restore).toBeVisible();
  await expect(restore.getByRole('button', { name: 'Keep it deleted' })).toBeFocused();
  await restore.getByRole('button', { name: 'Restore my account' }).click();

  await expect(page).toHaveURL('/library');
});

test('declining the restore keeps the learner signed out', async ({ page }) => {
  const state = await fakeAccountApi(page);
  state.signedIn = false;
  state.deleted = true;

  await page.goto('/sign-in');
  await page.getByLabel('Email').fill('learner@example.com');
  await page.getByLabel('Password').fill('correct horse');
  await page.getByLabel('Password').press('Enter');
  await page.keyboard.press('Escape');

  await expect(page.getByRole('dialog')).toBeHidden();
  await expect(page.getByRole('status')).toContainText('Your account stays deleted');
  await expect(page).toHaveURL('/sign-in');
});

test('the settings page fits a 360 px screen without sideways scrolling', async ({ page }) => {
  await fakeAccountApi(page);
  await page.setViewportSize({ width: 360, height: 740 });

  for (const path of ['/settings', '/account-deleted?until=2026-10-11T20%3A30%3A00Z']) {
    await page.goto(path);
    await expect(page.getByRole('main')).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, `horizontal overflow on ${path}`).toBeLessThanOrEqual(0);
  }
});
