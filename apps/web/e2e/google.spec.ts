import { expect, test } from '@playwright/test';

// Mocked browser navigation complements the API's signed-token tests.
test('keyboard Google navigation reloads into the authenticated account', async ({ page }) => {
  let signedIn = false;
  let started = false;
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/auth/oidc/google/start')) {
      expect(url.searchParams.get('next')).toBe('/library');
      started = true;
      signedIn = true;
      return route.fulfill({
        contentType: 'text/html',
        body: '<html><body><script>location.replace("/library")</script></body></html>',
      });
    }
    if (url.pathname.endsWith('/health')) return route.fulfill({ json: { status: 'ok' } });
    if (url.pathname.endsWith('/me')) {
      return route.fulfill({
        status: signedIn ? 200 : 401,
        json: signedIn
          ? {
              id: 'google-learner',
              email: 'google@example.com',
              display_name: null,
              email_verified: true,
              deletion_grace_days: 7,
            }
          : { status: 401, code: 'not_signed_in', detail: 'Sign in to continue.' },
      });
    }
    return route.fulfill({ json: { items: [], next_cursor: null } });
  });
  await page.goto('/sign-in');
  const google = page.getByRole('link', { name: 'Continue with Google' });
  await google.focus();
  await expect(google).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(/\/library$/);
  await expect(
    page.getByRole('heading', { name: 'Add your first clip', exact: true }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Account', exact: true }).click();
  await expect(page.getByText('google@example.com', { exact: true })).toBeVisible();
  expect(started).toBe(true);
});
