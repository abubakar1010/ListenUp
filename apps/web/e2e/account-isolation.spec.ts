import { expect, test } from '@playwright/test';

test('expired learner A data stays hidden while learner B library loads', async ({ page }) => {
  const learnerA = { id: 'a', email: 'a@example.com', display_name: null, email_verified: false };
  const learnerB = { ...learnerA, id: 'b', email: 'b@example.com' };
  const clipA = {
    id: 'a-clip',
    title: 'A private recording',
    source: 'upload',
    status: 'playable',
    duration_ms: 30_000,
    created_at: '2026-10-03T09:00:00Z',
    last_session_status: null,
  };
  const clipB = { ...clipA, id: 'b-clip', title: 'B private recording' };
  let signedIn: 'a' | 'b' | null = 'a';
  let releaseLibrary!: () => void;
  const libraryReady = new Promise<void>((resolve) => {
    releaseLibrary = resolve;
  });
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '');
    if (path === '/auth/login') {
      signedIn = 'b';
      return route.fulfill({ json: learnerB });
    }
    if (path === '/me') {
      if (signedIn !== null) return route.fulfill({ json: signedIn === 'b' ? learnerB : learnerA });
      return route.fulfill({
        status: 401,
        json: {
          type: '/problems/not_signed_in',
          title: 'Unauthorized',
          status: 401,
          code: 'not_signed_in',
          detail: 'Sign in to continue.',
        },
      });
    }
    if (path === '/library/contents') {
      if (new URL(route.request().url()).searchParams.has('cursor')) {
        signedIn = null;
        return route.fulfill({
          status: 401,
          json: {
            type: '/problems/not_signed_in',
            title: 'Unauthorized',
            status: 401,
            code: 'not_signed_in',
            detail: 'Sign in to continue.',
          },
        });
      }
      if (signedIn === 'b') {
        await libraryReady;
        return route.fulfill({ json: { items: [clipB], next_cursor: null } });
      }
      return route.fulfill({ json: { items: [clipA], next_cursor: 'next-a' } });
    }
    if (path === '/health')
      return route.fulfill({
        json: { status: 'ok' },
        headers: {
          'Set-Cookie': 'listenup_csrf=e2e-token; Path=/; SameSite=Lax',
        },
      });
    return route.fulfill({ json: { items: [], next_cursor: null } });
  });

  await page.goto('/library');
  await expect(page.getByRole('link', { name: clipA.title, exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Load more' }).click();
  await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible();
  await expect(page.getByText(clipA.title, { exact: true })).toHaveCount(0);

  await page.getByLabel('Email').fill(learnerB.email);
  await page.getByLabel('Password').fill('a good password');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Library', exact: true })).toBeVisible();
  await expect(page.getByText(clipA.title, { exact: true })).toHaveCount(0);
  releaseLibrary();
  await expect(page.getByRole('link', { name: clipB.title, exact: true })).toBeVisible();
  await expect(page.getByText(clipA.title, { exact: true })).toHaveCount(0);
});
