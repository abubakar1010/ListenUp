import { expect, test } from './test';

import type { components } from '../src/api/schema';
import { fakeApi } from './a11y/fakeApi';

const CLIP: components['schemas']['LibraryItem'] = {
  id: 'clip-89',
  title: 'My private clip',
  source: 'upload',
  status: 'playable',
  duration_ms: 120000,
  created_at: '2026-10-28T00:00:00Z',
  last_session_status: null,
};

test('content deletion confirms safely, blocks duplicate submits and retries errors', async ({
  page,
}) => {
  let removed = false;
  const unanswered = await fakeApi(
    page,
    {
      '/library/contents': () => ({ json: { items: removed ? [] : [CLIP], next_cursor: null } }),
    },
    true,
  );
  let release!: () => void;
  const pending = new Promise<void>((resolve) => {
    release = resolve;
  });
  let calls = 0;
  await page.route('**/api/v1/contents/clip-89', async (route) => {
    expect(route.request().method()).toBe('DELETE');
    expect(route.request().postDataJSON()).toEqual({ confirm: true });
    if (++calls === 1) {
      await pending;
      return route.fulfill({
        status: 503,
        json: {
          status: 503,
          code: 'unavailable',
          detail: 'Please retry deletion.',
        },
      });
    }
    removed = true;
    return route.fulfill({ status: 202, json: { request_id: 'request-89' } });
  });
  await page.goto('/library');
  const opener = page.getByRole('button', { name: 'Delete My private clip' });
  // Opened from the keyboard: Safari does not focus a button on a mouse click, so there
  // would be no focused opener to return to.
  await opener.focus();
  await opener.press('Enter');
  const dialog = page.getByRole('dialog', { name: 'Delete My private clip?' });
  await expect(dialog.getByRole('button', { name: 'Keep clip' })).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(dialog.getByRole('button', { name: 'Delete clip' })).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await expect(dialog.getByRole('button', { name: 'Keep clip' })).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  await expect(opener).toBeFocused();
  expect(calls).toBe(0);
  await opener.click();
  await dialog.getByRole('button', { name: 'Delete clip' }).click();
  await expect(dialog.getByRole('button', { name: 'Requesting deletion…' })).toBeDisabled();
  await expect(dialog.getByRole('button', { name: 'Keep clip' })).toBeDisabled();
  await page.keyboard.press('Escape');
  await expect(dialog).toBeVisible();
  release();
  await expect(dialog.getByRole('alert')).toContainText('Please retry deletion.');
  await dialog.getByRole('button', { name: 'Delete clip' }).click();
  await expect(page.getByRole('heading', { name: 'Add your first clip' })).toBeVisible();
  await expect(page.getByRole('status')).toContainText('Clip deletion requested.');
  expect(calls).toBe(2);
  expect(unanswered).toEqual([]);
});
