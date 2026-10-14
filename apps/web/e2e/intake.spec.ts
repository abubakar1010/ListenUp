import { expect, test, type Page, type Route } from '@playwright/test';

/*
 * Intake status and refusals (#39, #40, #41), with the API answered by the test.
 */

const LEARNER = {
  id: '1',
  email: 'learner@example.com',
  display_name: null,
  email_verified: false,
  deletion_grace_days: 7,
};

const CLIP = {
  id: 'content-1',
  title: 'Morning news',
  source: 'upload',
  duration_ms: null,
  created_at: '2026-10-03T09:00:00Z',
  last_session_status: null,
};

const DETAIL = {
  media_object_id: 'media-1',
  has_video: false,
  keep_video: false,
  error_code: null,
  error_detail: null,
  media_url: null,
  peaks_url: null,
};

const MB = 2 ** 20;

function problem(route: Route, status: number, code: string, detail: string, extra = {}) {
  return route.fulfill({
    status,
    contentType: 'application/problem+json',
    json: { type: `/problems/${code}`, title: '', status, detail, code, ...extra },
  });
}

/** Answers what every signed-in page needs; `handle` answers the rest, or 404. */
async function fakeApi(page: Page, handle: (path: string, route: Route) => Promise<void> | null) {
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '');
    if (path === '/health') {
      return route.fulfill({
        json: { status: 'ok' },
        headers: { 'Set-Cookie': 'listenup_csrf=e2e-token; Path=/; SameSite=Lax' },
      });
    }
    if (path === '/me') return route.fulfill({ json: LEARNER });
    if (path === '/sessions') return route.fulfill({ json: { items: [], next_cursor: null } });
    const handled = handle(path, route);
    if (handled) return handled;
    return problem(route, 404, 'not_found', path);
  });
}

test('a clip moves from converting to ready live, and a notice says it is ready', async ({
  page,
}) => {
  let ready = false;
  let releaseEvents: () => void = () => undefined;
  const eventsReleased = new Promise<void>((resolve) => (releaseEvents = resolve));

  await fakeApi(page, (path, route) => {
    if (path === '/library/contents') {
      const item = ready
        ? { ...CLIP, status: 'playable', duration_ms: 60_000, stage: null }
        : { ...CLIP, status: 'pending', stage: 'converting', queue_position: null };
      return route.fulfill({ json: { items: [item], next_cursor: null } });
    }
    if (path === '/contents/content-1') {
      return route.fulfill({
        json: { ...CLIP, ...DETAIL, status: 'playable', duration_ms: 60_000, stage: null },
      });
    }
    if (path === '/events') {
      // One event, then the stream ends; the browser would reconnect after a minute.
      return eventsReleased.then(() => {
        ready = true;
        return route.fulfill({
          status: 200,
          contentType: 'text/event-stream',
          body:
            'retry: 60000\n\n' +
            'id: hub-1\nevent: content.ready\n' +
            'data: {"type": "content.ready", "resource_id": "content-1"}\n\n',
        });
      });
    }
    return null;
  });

  await page.goto('/library');
  const row = page.getByRole('listitem').filter({ hasText: 'Morning news' });
  await expect(row).toContainText('Converting');
  const focused = await page.evaluate(() => document.activeElement?.tagName);

  releaseEvents();

  await expect(row).toContainText('Ready');
  const notice = page.getByText('\u201cMorning news\u201d is ready to practise.');
  await expect(notice).toBeVisible();
  // Announced politely, without moving focus.
  await expect(page.locator('[aria-live="polite"]').filter({ has: notice })).toHaveCount(1);
  expect(await page.evaluate(() => document.activeElement?.tagName)).toBe(focused);

  await page.getByRole('link', { name: 'Open the clip' }).click();
  await expect(page).toHaveURL('/contents/content-1');
  await expect(notice).toHaveCount(0);
});

test("a new file is refused before upload once today's new audio is used up", async ({ page }) => {
  let posted = false;
  await fakeApi(page, (path, route) => {
    if (path === '/library/contents') {
      return route.fulfill({ json: { items: [], next_cursor: null } });
    }
    if (path === '/uploads/usage') {
      return route.fulfill({
        json: {
          used_bytes: 300 * MB,
          quota_bytes: 2048 * MB,
          max_file_bytes: 500 * MB,
          daily_audio: {
            used_seconds: 7200,
            limit_seconds: 7200,
            clips_in_progress: 0,
            reserved_seconds: 0,
            can_add: false,
            resets_at: '2030-01-01T00:00:00Z',
          },
        },
      });
    }
    if (path === '/uploads') {
      posted = true;
      return problem(route, 429, 'daily_audio_limit', 'Daily limit.');
    }
    return null;
  });
  await page.setViewportSize({ width: 360, height: 740 });

  await page.goto('/library/add');
  await expect(page.getByText(/120 of 120 minutes of new audio added today/)).toBeVisible();
  await page.locator('input[type="file"]').setInputFiles({
    name: 'talk.mp3',
    mimeType: 'audio/mpeg',
    buffer: Buffer.alloc(1024, 1),
  });

  const alert = page.getByRole('alert');
  await expect(alert).toContainText("You have reached today's limit of new audio");
  await expect(alert).toContainText(
    /You have added 120 minutes of new audio today, the daily limit\. You can add more at \d\d:\d\d/,
  );
  expect(posted).toBe(false);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
});

test('a server refusal names the problem and what to do', async ({ page }) => {
  await fakeApi(page, (path, route) => {
    if (path === '/uploads/usage') {
      return route.fulfill({
        json: { used_bytes: 0, quota_bytes: 2048 * MB, max_file_bytes: 500 * MB },
      });
    }
    if (path === '/uploads') {
      return problem(
        route,
        422,
        'storage_full',
        'You have used 1.9 GB of 2.0 GB, and this file is 184 MB. Delete a clip you have finished to make room.',
      );
    }
    return null;
  });

  await page.goto('/library/add');
  await page.locator('input[type="file"]').setInputFiles({
    name: 'talk.mp3',
    mimeType: 'audio/mpeg',
    buffer: Buffer.alloc(1024, 1),
  });

  const alert = page.getByRole('alert');
  await expect(alert.getByRole('heading')).toHaveText('Your upload storage is full');
  await expect(alert).toContainText('Delete a clip you have finished to make room.');
});

test('the page of a removed copy links to the clip the learner has', async ({ page }) => {
  await fakeApi(page, (path, route) => {
    if (path === '/contents/content-2') {
      return problem(
        route,
        410,
        'duplicate_upload',
        'You already have this clip in your library, as \u201cMorning news\u201d, so this copy was not added. Open that clip to practise it.',
        { existing_content_id: 'content-1', existing_title: 'Morning news' },
      );
    }
    if (path === '/contents/content-1') {
      return route.fulfill({
        json: { ...CLIP, ...DETAIL, status: 'pending', stage: 'queued', queue_position: 2 },
      });
    }
    return null;
  });

  await page.goto('/contents/content-2');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('You already have this clip');
  await page.getByRole('link', { name: 'Open Morning news' }).click();

  await expect(page).toHaveURL('/contents/content-1');
  await expect(page.getByRole('status')).toContainText(
    'Waiting for your other clips: two of your clips are prepared at a time. It is 2nd in line.',
  );
});
