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
    if (signedIn) {
      // Endpoints this test does not fake: an empty answer, not a sign-out.
      if (path === '/library/contents')
        return route.fulfill({ json: { items: [], next_cursor: null } });
      return route.fulfill({
        status: 404,
        contentType: 'application/problem+json',
        json: {
          type: '/problems/not_found',
          title: 'Not Found',
          status: 404,
          detail: path,
          code: 'not_found',
        },
      });
    }
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

  for (const path of ['/library', '/library/add', '/sessions/abc-123', '/no-such-page']) {
    await page.goto(path);
    await expect(page.getByRole('main')).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, `horizontal overflow on ${path}`).toBeLessThanOrEqual(0);
  }
});

test('a learner uploads a clip with progress and sees it in the library', async ({ page }) => {
  const items: object[] = [];
  let putBody = 0;
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
    if (path === '/me') return route.fulfill({ json: LEARNER });
    if (path === '/library/contents') return route.fulfill({ json: { items, next_cursor: null } });
    if (path === '/uploads/usage') {
      return route.fulfill({
        json: { used_bytes: 0, quota_bytes: 2 ** 31, max_file_bytes: 500 * 2 ** 20 },
      });
    }
    if (path === '/uploads' && method === 'POST') {
      return route.fulfill({
        status: 201,
        json: {
          upload_id: 'up-1',
          url: 'http://storage.e2e.test/listenup/users/1/uploads/up-1.mp3?X-Amz-Signature=x',
          method: 'PUT',
          headers: { 'Content-Type': 'audio/mpeg' },
          expires_at: '2030-01-01T00:00:00Z',
        },
      });
    }
    if (path === '/contents' && method === 'POST') {
      const item = {
        id: 'content-1',
        title: 'street-trees-talk',
        source: 'upload',
        status: 'pending',
        duration_ms: null,
        created_at: '2026-10-03T09:00:00Z',
      };
      items.push({ ...item, last_session_status: null });
      return route.fulfill({ status: 201, json: item });
    }
    return route.fulfill({ status: 404, json: { code: 'not_found', detail: path } });
  });
  // Object storage: answers the CORS preflight and takes the PUT.
  await page.route('http://storage.e2e.test/**', async (route) => {
    const cors = {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'PUT',
      'Access-Control-Allow-Headers': 'content-type',
    };
    if (route.request().method() === 'PUT') putBody = route.request().postDataBuffer()?.length ?? 0;
    return route.fulfill({ status: 200, headers: cors, body: '' });
  });

  await page.goto('/library');
  await expect(page.getByRole('heading', { name: 'Add your first clip' })).toBeVisible();
  await page.getByRole('link', { name: 'Upload a file' }).click();
  await expect(page).toHaveTitle('Add a clip · ListenUp');

  await page.locator('input[type="file"]').setInputFiles({
    name: 'street-trees-talk.mp3',
    mimeType: 'audio/mpeg',
    buffer: Buffer.alloc(256 * 1024, 1),
  });

  await expect(page).toHaveURL('/library');
  const clip = page.getByRole('listitem').filter({ hasText: 'street-trees-talk' });
  await expect(clip).toContainText('Processing');
  expect(putBody).toBe(256 * 1024);
});

test('a file of the wrong type is refused before it is sent', async ({ page }) => {
  await fakeApi(page, { signedIn: true });
  await page.setViewportSize({ width: 360, height: 740 });
  await page.goto('/library/add');

  await page.getByRole('button', { name: 'Choose a file' }).focus();
  await page.locator('input[type="file"]').setInputFiles({
    name: 'notes.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF'),
  });

  await expect(page.getByRole('alert')).toContainText("notes.pdf can't be used");
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
});
