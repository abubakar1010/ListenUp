import { expect, test } from './test';

function audibleSnippet() {
  const rate = 8000;
  const buffer = Buffer.alloc(44 + rate * 3 * 2);
  buffer.write('RIFF', 0);
  buffer.writeUInt32LE(buffer.length - 8, 4);
  buffer.write('WAVEfmt ', 8);
  buffer.writeUInt32LE(16, 16);
  buffer.writeUInt16LE(1, 20);
  buffer.writeUInt16LE(1, 22);
  buffer.writeUInt32LE(rate, 24);
  buffer.writeUInt32LE(rate * 2, 28);
  buffer.writeUInt16LE(2, 32);
  buffer.writeUInt16LE(16, 34);
  buffer.write('data', 36);
  buffer.writeUInt32LE(buffer.length - 44, 40);
  for (let i = 0; i < rate * 3; i++)
    buffer.writeInt16LE(Math.round(Math.sin((i * 2 * Math.PI * 440) / rate) * 1000), 44 + i * 2);
  return buffer;
}

// Browser behavior against a mocked API; DB limits are proved by test_cards_api.py.
for (const refreshFails of [false, true]) {
  test(`cards_keyboard_at_360px (count refresh fails: ${refreshFails})`, async ({ page }) => {
    await page.setViewportSize({ width: 360, height: 800 });
    let done = false;
    const cards: Record<string, unknown>[] = [];
    let writes = 0;
    let deleted = false;
    let releaseList: (() => void) | undefined;
    await page.route('**/api/v1/**', async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const path = url.pathname.replace('/api/v1', '');
      if (path.endsWith('/audio'))
        return route.fulfill({ contentType: 'audio/wav', body: audibleSnippet() });
      if (path === '/me')
        return route.fulfill({
          json: {
            id: 'learner',
            email: 'test@example.com',
            consents_required: [],
            display_name: null,
            email_verified: false,
          },
        });
      if (path === '/events')
        return route.fulfill({ contentType: 'text/event-stream', body: ': open\n\n' });
      if (path === '/sessions/s-72')
        return route.fulfill({
          json: {
            id: 's-72',
            content_id: 'c-72',
            content_title: 'Card practice',
            passage: { start_ms: 0, end_ms: 30000 },
            entry: 'blind',
            status: 'active',
            version: done ? 3 : 2,
            steps: [
              { step: 'blind', position: 1, status: 'done' },
              { step: 'transcript', position: 2, status: 'done' },
              { step: 'card', position: 3, status: done ? 'done' : 'open' },
              { step: 'shadow', position: 4, status: done ? 'open' : 'locked' },
            ],
            step_count: 4,
            open_step: done ? 'shadow' : 'card',
            open_position: done ? 4 : 3,
            entry_locked: true,
            entry_locked_at: null,
            completed_at: null,
            created_at: '2026-10-23T00:00:00Z',
            updated_at: '2026-10-23T00:00:00Z',
          },
        });
      if (path.endsWith('/marks'))
        return route.fulfill({
          json: { marks: [{ id: 'm-72', word_from: 0, word_to: 1, at_ms: 11000, note: null }] },
        });
      if (path.endsWith('/transcript'))
        return route.fulfill({
          json: {
            lines: [
              {
                words: [
                  { index: 0, text: 'could' },
                  { index: 1, text: 'have' },
                ],
              },
            ],
          },
        });
      if (path === '/cards' && request.method() === 'GET') {
        if (deleted)
          await new Promise<void>((resolve) => {
            releaseList = resolve;
          });
        if (refreshFails && writes === 2 && !deleted)
          return route.fulfill({
            status: 503,
            json: { status: 503, code: 'unavailable', detail: 'Cards unavailable' },
          });
        return route.fulfill({ json: { cards, remaining: 2 - cards.length, next_cursor: null } });
      }
      if (path === '/sessions/s-72/cards') {
        writes++;
        const card = {
          ...request.postDataJSON(),
          audio_status: 'ready',
          id: `card-${writes}`,
          source_url: '/contents/c-72?at_ms=11000',
          at_ms: 11000,
        };
        cards.push(card);
        return route.fulfill({ status: 201, json: card });
      }
      if (path.startsWith('/cards/') && request.method() === 'DELETE') {
        deleted = true;
        cards.splice(
          cards.findIndex((card) => card.id === path.split('/').at(-1)),
          1,
        );
        return route.fulfill({ status: 204 });
      }
      if (path.endsWith('/cards/complete')) {
        done = true;
        return route.fulfill({ status: 204 });
      }
      return route.fulfill({
        status: 404,
        json: { status: 404, code: 'not_found', detail: 'No fixture' },
      });
    });
    await page.goto('/sessions/s-72');
    await expect(page.getByRole('option', { name: /could have/ })).toBeAttached();
    await expect(page.getByText('2 left', { exact: true })).toBeVisible();
    const select = page.getByRole('combobox', { name: 'Marked phrase' });
    await select.focus();
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('Tab');
    await expect(page.getByRole('textbox', { name: 'Written form' })).toBeFocused();
    await expect(page.getByRole('textbox', { name: 'Written form' })).toHaveValue('could have');
    await page.keyboard.press('Tab');
    await page.keyboard.type('kuduv');
    await page.keyboard.press('Tab');
    await expect(page.getByRole('button', { name: 'Save card' })).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(page.getByText('1 left', { exact: true }).first()).toBeVisible();
    const play = page.getByRole('button', { name: 'Play audio: could have', exact: true });
    await play.focus();
    await page.keyboard.press('Enter');
    const pause = page.getByRole('button', { name: 'Pause audio: could have', exact: true });
    await expect(pause).toBeFocused();
    await expect
      .poll(() =>
        page.locator('audio').evaluate((element) => (element as HTMLAudioElement).currentTime),
      )
      .toBeGreaterThan(0);
    await page.keyboard.press('Space');
    await expect(play).toBeFocused();
    await expect
      .poll(() => page.locator('audio').evaluate((element) => (element as HTMLAudioElement).paused))
      .toBe(true);
    await page.getByRole('textbox', { name: 'Heard form' }).fill('kuduv');
    await page.getByRole('button', { name: 'Save card' }).press('Enter');
    await expect(page.getByText('0 left', { exact: true }).first()).toBeVisible();
    // The confirmed write updates the count before its failed refresh settles.
    // Wait for mutation completion, rather than observing the stale pre-click label.
    await expect(page.locator('form')).toHaveAttribute('aria-busy', 'false', { timeout: 15000 });
    await expect(page.getByRole('button', { name: 'Save card' })).toHaveAttribute(
      'aria-disabled',
      'true',
    );
    await page.getByRole('button', { name: 'Save card' }).press('Enter');
    expect(writes).toBe(2);
    await page
      .getByRole('button', { name: /Delete card:/ })
      .first()
      .press('Enter');
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('button', { name: 'Keep card' })).toBeFocused();
    await page.keyboard.press('Escape');
    await expect(page.getByRole('button', { name: /Delete card:/ }).first()).toBeFocused();
    await page.keyboard.press('Enter');
    await dialog.getByRole('button', { name: 'Delete card', exact: true }).press('Enter');
    await expect.poll(() => releaseList !== undefined).toBe(true);
    await expect(dialog).toHaveCount(0);
    await expect(page.getByRole('main')).toBeFocused();
    await expect(page.getByText('1 left', { exact: true }).first()).toBeVisible();
    releaseList!();
    await expect(page.getByRole('button', { name: /Delete card:/ })).toHaveCount(1);
    await expect(page.getByRole('main')).toBeFocused();
    await expect(page.getByRole('button', { name: 'Save card' })).toHaveAttribute(
      'aria-disabled',
      'false',
    );
    await expect(page.getByRole('link', { name: 'Source at 00:11' })).toHaveAttribute(
      'href',
      '/contents/c-72?at_ms=11000',
    );
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
    await expect(page.getByLabel(/Definition|Translation/)).toHaveCount(0);
    await page.getByRole('button', { name: 'Finish Card' }).press('Enter');
    await expect(page.getByRole('heading', { name: /Shadow: Card practice/ })).toBeAttached();
  });
}
