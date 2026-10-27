import { expect, test } from '@playwright/test';
import { sessionFixture } from '../src/features/session/fixtures';

for (const duration of [45_000, 150_000]) {
  test(`Shadow keyboard selection at 360 px for a ${duration / 1000}s passage`, async ({
    page,
  }) => {
    const session = sessionFixture({
      done: 3,
      passage: { start_ms: 10_000, end_ms: 10_000 + duration },
    });
    let segment = {
      session_id: session.id,
      start_ms: 10_000,
      end_ms: 10_000 + Math.min(90_000, duration),
      chosen_by: 'system',
      mark_count: 3,
      locked_at: null,
    };
    const writes: unknown[] = [];
    await page.route('**/api/v1/**', async (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname.replace('/api/v1', '');
      if (path === '/auth/consent-versions')
        return route.fulfill({ json: { voice_recording: 'voice-2026-1' } });
      if (path === '/me/consents')
        return route.fulfill({
          json: {
            consents: [{ kind: 'voice_recording', version: 'voice-2026-1', withdrawn_at: null }],
          },
        });
      if (path === '/health')
        return route.fulfill({
          json: { status: 'ok' },
          headers: { 'Set-Cookie': 'listenup_csrf=e2e-token; Path=/; SameSite=Lax' },
        });
      if (path === '/me')
        return route.fulfill({
          json: {
            id: '1',
            email: 'learner@example.com',
            display_name: null,
            email_verified: true,
            deletion_grace_days: 7,
            consents_required: [],
          },
        });
      if (path === `/sessions/${session.id}`) return route.fulfill({ json: session });
      if (path === `/sessions/${session.id}/shadow/rounds`)
        return route.fulfill({ json: { segment, current: null, rounds: [] } });
      if (path === `/sessions/${session.id}/shadow/segment`) {
        if (request.method() === 'PUT') {
          writes.push(request.postDataJSON());
          segment = { ...segment, ...request.postDataJSON(), chosen_by: 'learner' };
        }
        return route.fulfill({ json: segment });
      }
      if (path === '/contents/clip-1')
        return route.fulfill({
          json: { id: 'clip-1', media_url: '/api/v1/media/m-1', peaks_url: null },
        });
      if (path === '/media/m-1') {
        const audio = wav();
        const requested = /bytes=(\d+)-(\d*)/.exec(request.headers()['range'] ?? '');
        const from = requested ? Number(requested[1]) : 0;
        const to = requested?.[2] ? Number(requested[2]) : audio.length - 1;
        return route.fulfill({
          status: requested ? 206 : 200,
          headers: {
            'Content-Type': 'audio/wav',
            'Accept-Ranges': 'bytes',
            ...(requested ? { 'Content-Range': `bytes ${from}-${to}/${audio.length}` } : {}),
          },
          body: audio.subarray(from, to + 1),
        });
      }
      return route.fulfill({ status: 404, json: { code: 'not_found' } });
    });
    await page.setViewportSize({ width: 360, height: 800 });
    await page.goto(`/sessions/${session.id}`);
    await expect(page.getByRole('heading', { name: 'Your Shadow segment' })).toBeVisible();
    if (duration === 45_000) {
      await expect(
        page.getByText('This passage is 60 seconds or shorter, so Shadow uses the whole passage.'),
      ).toBeVisible();
      await expect(page.getByRole('slider', { name: /Segment (start|end)/ })).toHaveCount(0);
      expect(writes).toEqual([]);
    } else {
      const start = page.getByRole('slider', { name: 'Segment start' });
      await start.focus();
      await start.press('End');
      await expect(start).toHaveAttribute('aria-valuenow', '30');
      await page.keyboard.press('Tab');
      const end = page.getByRole('slider', { name: 'Segment end' });
      await expect(end).toBeFocused();
      await end.press('End');
      await page.keyboard.press('Tab');
      await expect(page.getByRole('button', { name: 'Save segment' })).toBeFocused();
      await page.keyboard.press('Enter');
      await expect(page.getByText('Segment saved.')).toBeVisible();
      expect(writes).toEqual([{ start_ms: 40_000, end_ms: 130_000 }]);
      await page.reload();
      await expect(page.getByRole('slider', { name: 'Segment start' })).toHaveAttribute(
        'aria-valuenow',
        '30',
      );
      await expect(page.getByRole('button', { name: 'Play', exact: true })).toBeEnabled();
      await page.getByRole('slider', { name: 'Seek', exact: true }).fill('50000');
      await page.getByRole('button', { name: 'Replay selected segment' }).click();
      await expect
        .poll(() => page.locator('audio').evaluate((audio: HTMLAudioElement) => audio.currentTime))
        .toBeGreaterThanOrEqual(40);
      expect(
        await page.locator('audio').evaluate((audio: HTMLAudioElement) => audio.currentTime),
      ).toBeLessThan(42);
      await page.locator('audio').evaluate((audio: HTMLAudioElement) => {
        audio.currentTime = 130.1;
        audio.dispatchEvent(new Event('timeupdate'));
      });
      await expect
        .poll(() => page.locator('audio').evaluate((audio: HTMLAudioElement) => audio.paused))
        .toBe(true);
    }
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      ),
    ).toBeLessThanOrEqual(0);
  });
}

test('three Shadow rounds use keyboard controls at 360 px and original speed', async ({ page }) => {
  const session = sessionFixture({ done: 3, passage: { start_ms: 10000, end_ms: 55000 } });
  const segment = {
    session_id: session.id,
    start_ms: 10000,
    end_ms: 55000,
    chosen_by: 'system',
    mark_count: 0,
    locked_at: null as string | null,
  };
  let granted = false;
  const rounds: {
    round: number;
    transcript_shown: boolean;
    playback_status: string;
    recorded_at: null;
  }[] = [];
  const root = `/sessions/${session.id}/shadow/rounds`;
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace('/api/v1', '');
    if (path === '/auth/consent-versions')
      return route.fulfill({ json: { voice_recording: 'voice-2026-1' } });
    if (path === '/me/consents') {
      if (request.method() === 'POST') {
        expect(request.postDataJSON()).toEqual({
          kind: 'voice_recording',
          version: 'voice-2026-1',
        });
        granted = true;
      }
      return route.fulfill({
        json: {
          consents: granted
            ? [{ kind: 'voice_recording', version: 'voice-2026-1', withdrawn_at: null }]
            : [],
        },
      });
    }
    if (path === '/health')
      return route.fulfill({
        json: { status: 'ok' },
        headers: { 'Set-Cookie': 'listenup_csrf=e2e; Path=/; SameSite=Lax' },
      });
    if (path === '/me')
      return route.fulfill({
        json: {
          id: '1',
          email: 'learner@example.com',
          display_name: null,
          email_verified: true,
          deletion_grace_days: 7,
          consents_required: [],
        },
      });
    if (path === `/sessions/${session.id}`) return route.fulfill({ json: session });
    if (path === `/sessions/${session.id}/shadow/segment`) return route.fulfill({ json: segment });
    if (path === root)
      return route.fulfill({
        json: {
          segment,
          rounds,
          current: rounds.at(-1) ?? null,
          ...(rounds.at(-1)?.round === 1
            ? { text: 'Only the first round reveals these words.' }
            : {}),
        },
      });
    if (path.startsWith(root + '/') && request.method() === 'POST') {
      const number = Number(path.split('/').at(-2));
      if (path.endsWith('/start')) {
        rounds.push({
          round: number,
          transcript_shown: number === 1,
          playback_status: 'ready',
          recorded_at: null,
        });
        segment.locked_at = '2026-10-25T10:00:00Z';
      } else rounds[number - 1].playback_status = 'ended';
      return route.fulfill({ status: 204 });
    }
    if (path === '/contents/clip-1')
      return route.fulfill({
        json: { id: 'clip-1', media_url: '/api/v1/media/m-1', peaks_url: null },
      });
    if (path === '/media/m-1') {
      const audio = wav();
      const requested = /bytes=(\d+)-(\d*)/.exec(request.headers()['range'] ?? '');
      const from = requested ? Number(requested[1]) : 0;
      const to = requested?.[2] ? Number(requested[2]) : audio.length - 1;
      return route.fulfill({
        status: requested ? 206 : 200,
        headers: {
          'Content-Type': 'audio/wav',
          'Accept-Ranges': 'bytes',
          ...(requested ? { 'Content-Range': `bytes ${from}-${to}/${audio.length}` } : {}),
        },
        body: audio.subarray(from, to + 1),
      });
    }
    return route.fulfill({ status: 404, json: { code: 'not_found' } });
  });
  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto(`/sessions/${session.id}`);
  const mic = page.getByRole('button', { name: 'Check microphone' });
  await mic.focus();
  await mic.press('Enter');
  await expect(page.getByText('Microphone ready. Sound detected.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Start round 1', exact: true })).toHaveAttribute(
    'aria-disabled',
    'true',
  );
  const agreement = page.getByRole('checkbox', { name: /I agree/ });
  await agreement.focus();
  await agreement.press('Space');
  await page.keyboard.press('Tab');
  const accept = page.getByRole('button', { name: 'Agree to voice recording' });
  await expect(accept).toBeFocused();
  await accept.press('Enter');
  await expect(page.getByText(/You agreed to this version/)).toBeFocused();
  await expect(
    page.getByRole('link', { name: 'Voice recording consent', exact: true }),
  ).toHaveAttribute('href', '/voice-consent');
  expect(granted).toBe(true);
  for (const number of [1, 2, 3]) {
    const start = page.getByRole('button', { name: `Start round ${number}`, exact: true });
    await start.focus();
    await start.press('Enter');
    await expect(page.getByRole('heading', { name: `Round ${number} of 3` })).toBeFocused();
    const transcript = page.getByText('Only the first round reveals these words.');
    if (number === 1) await expect(transcript).toBeVisible();
    else await expect(transcript).toHaveCount(0);
    await expect(page.locator('audio')).toHaveCount(1);
    const play = page.getByRole('button', { name: `Play round ${number}`, exact: true });
    await expect(play).toBeEnabled();
    await play.focus();
    await expect(play).toBeFocused();
    await page.keyboard.press('Space');
    await expect(
      page.getByRole('status').filter({ hasText: `Round ${number} starts in 3` }),
    ).toBeVisible();
    await expect
      .poll(() => page.locator('audio').evaluate((audio: HTMLAudioElement) => audio.paused))
      .toBe(true);
    await expect(
      page.getByRole('status').filter({ hasText: 'playing at original speed' }),
    ).toBeVisible();
    await expect(page.getByRole('status')).toHaveCount(1);
    await page.locator('audio').evaluate((audio: HTMLAudioElement) => {
      audio.playbackRate = 1.5;
    });
    await expect
      .poll(() => page.locator('audio').evaluate((audio: HTMLAudioElement) => audio.playbackRate))
      .toBe(1);
    await page.locator('audio').evaluate((audio: HTMLAudioElement) => {
      audio.currentTime = 55.1;
      audio.dispatchEvent(new Event('timeupdate'));
    });
    await expect(page.getByText('Playback ended. Feedback unavailable.')).toBeVisible();
    expect(rounds[number - 1].recorded_at).toBeNull();
  }
  await expect(page.getByRole('button', { name: 'Start round 4' })).toHaveCount(0);
  await expect(page.getByText(/No recording has been saved/)).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    ),
  ).toBe(0);
});

function wav(): Buffer {
  const samples = 200 * 8000;
  const buffer = Buffer.alloc(44 + samples, 128);
  buffer.write('RIFF', 0);
  buffer.writeUInt32LE(36 + samples, 4);
  buffer.write('WAVEfmt ', 8);
  buffer.writeUInt32LE(16, 16);
  buffer.writeUInt16LE(1, 20);
  buffer.writeUInt16LE(1, 22);
  buffer.writeUInt32LE(8000, 24);
  buffer.writeUInt32LE(8000, 28);
  buffer.writeUInt16LE(1, 32);
  buffer.writeUInt16LE(8, 34);
  buffer.write('data', 36);
  buffer.writeUInt32LE(samples, 40);
  return buffer;
}

test('denied microphone permission recovers through the confirmed skip path', async ({ page }) => {
  const session = sessionFixture({ done: 3 });
  let confirmed = false;
  const segment = {
    session_id: session.id,
    start_ms: 0,
    end_ms: 60000,
    mark_count: 0,
    chosen_by: 'system',
    locked_at: null,
  };
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '');
    if (path === '/health')
      return route.fulfill({
        json: { status: 'ok' },
        headers: { 'Set-Cookie': 'listenup_csrf=e2e; Path=/; SameSite=Lax' },
      });
    if (path === '/me')
      return route.fulfill({
        json: {
          id: '1',
          email: 'learner@example.com',
          display_name: null,
          email_verified: true,
          consents_required: [],
        },
      });
    if (path === '/auth/consent-versions')
      return route.fulfill({ json: { voice_recording: 'voice-2026-1' } });
    if (path === '/me/consents') return route.fulfill({ json: { consents: [] } });
    if (path === `/sessions/${session.id}`) return route.fulfill({ json: session });
    if (path === `/sessions/${session.id}/shadow/segment`) return route.fulfill({ json: segment });
    if (path === `/sessions/${session.id}/shadow/rounds`)
      return route.fulfill({ json: { segment, current: null, rounds: [] } });
    if (path === '/contents/clip-1')
      return route.fulfill({ json: { id: 'clip-1', media_url: null, peaks_url: null } });
    if (path.endsWith('/steps/shadow/skip')) {
      confirmed = route.request().postDataJSON().confirmed;
      return route.fulfill({
        json: { ...session, completed_at: '2026-10-26T10:00:00Z', open_step: null },
      });
    }
    return route.fulfill({ status: 404, json: { code: 'not_found' } });
  });
  await page.goto(`/sessions/${session.id}`);
  const cdp = await page.context().newCDPSession(page);
  const { targetInfo } = await cdp.send('Target.getTargetInfo');
  await cdp.send('Browser.setPermission', {
    browserContextId: targetInfo.browserContextId,
    permission: { name: 'microphone' },
    setting: 'denied',
    origin: new URL(page.url()).origin,
  });
  const check = page.getByRole('button', { name: 'Check microphone' });
  await check.focus();
  await check.press('Enter');
  await expect(page.getByText(/Microphone access was denied/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Start round 1' })).toHaveAttribute(
    'aria-disabled',
    'true',
  );
  const skip = page.getByRole('button', { name: 'Skip Shadow', exact: true });
  await skip.focus();
  await skip.press('Enter');
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Do Shadow', exact: true })).toBeFocused();
  expect(confirmed).toBe(false);
  const confirm = page
    .getByRole('dialog')
    .getByRole('button', { name: 'Skip Shadow and finish', exact: true });
  await confirm.focus();
  await confirm.press('Enter');
  await expect.poll(() => confirmed).toBe(true);
});
