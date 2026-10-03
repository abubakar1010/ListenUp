import { expect, test, type Page } from '@playwright/test';

const LEARNER = {
  id: '1',
  email: 'learner@example.com',
  display_name: null,
  email_verified: false,
};

/** Answers the API in the browser: signed out until the login call succeeds. */
async function fakeApi(page: Page, { signedIn = false } = {}) {
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '');
    if (path === '/health') {
      return route.fulfill({
        json: { status: 'ok' },
        headers: { 'Set-Cookie': 'listenup_csrf=e2e-token; Path=/; SameSite=Lax' },
      });
    }
    if (path === '/auth/login') {
      signedIn = true;
      return route.fulfill({ json: LEARNER });
    }
    if (path === '/me' && signedIn) return route.fulfill({ json: LEARNER });
    return route.fulfill({
      status: 401,
      contentType: 'application/problem+json',
      json: {
        type: '/problems/not_signed_in',
        title: 'Unauthorized',
        status: 401,
        detail: 'Sign in to continue.',
        code: 'not_signed_in',
      },
    });
  });
}

test('a signed-out learner opens a session, signs in and lands back on it', async ({ page }) => {
  await fakeApi(page);

  await page.goto('/sessions/abc-123');

  await expect(page).toHaveURL('/sign-in?next=%2Fsessions%2Fabc-123');
  await expect(page).toHaveTitle('Sign in · ListenUp');

  // The first Tab reaches the skip link.
  await page.keyboard.press('Tab');
  await expect(page.getByRole('link', { name: 'Skip to content' })).toBeFocused();

  await page.getByLabel('Email').fill('learner@example.com');
  await page.getByLabel('Password').fill('correct horse');
  await page.getByLabel('Password').press('Enter');

  await expect(page).toHaveURL('/sessions/abc-123');
  await expect(page).toHaveTitle('Practice · ListenUp');
  const main = page.getByRole('main');
  // Focus moves to the new page's content after the learner's own navigation.
  await expect(main).toBeFocused();
  await expect(main.getByRole('region', { name: 'Plan progress' })).toBeVisible();
  await expect(main.getByRole('region', { name: 'Player' })).toBeVisible();
  await expect(main.getByRole('region', { name: 'Practice' })).toBeVisible();
});

test('the shell fits a 360 px screen without sideways scrolling', async ({ page }) => {
  await fakeApi(page, { signedIn: true });
  await page.setViewportSize({ width: 360, height: 740 });

  for (const path of ['/library', '/sessions/abc-123', '/no-such-page']) {
    await page.goto(path);
    await expect(page.getByRole('main')).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, `horizontal overflow on ${path}`).toBeLessThanOrEqual(0);
  }
});
