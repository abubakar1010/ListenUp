import { denyMicrophone, expect, skipWithoutMediaRecorder, test } from './test';
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
        .poll(() =>
          page
            .locator('audio:not([controls])')
            .evaluate((audio: HTMLAudioElement) => audio.currentTime),
        )
        .toBeGreaterThanOrEqual(40);
      expect(
        await page
          .locator('audio:not([controls])')
          .evaluate((audio: HTMLAudioElement) => audio.currentTime),
      ).toBeLessThan(42);
      await page.locator('audio:not([controls])').evaluate((audio: HTMLAudioElement) => {
        audio.currentTime = 130.1;
        audio.dispatchEvent(new Event('timeupdate'));
      });
      await expect
        .poll(() =>
          page.locator('audio:not([controls])').evaluate((audio: HTMLAudioElement) => audio.paused),
        )
        .toBe(true);
    }
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      ),
    ).toBeLessThanOrEqual(0);
  });
}

// AT-6, AT-16, NFR-COM-1: the recording is Opus in WebM where the browser can make it
// and AAC in MP4 where it cannot (older Safari), which the second variant forces.
for (const variant of ['browser default', 'WebM refused (older Safari)'] as const) {
  test(`three Shadow rounds use keyboard controls at 360 px and original speed (${variant})`, async ({
    page,
    browserName,
  }) => {
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
      id: string;
      round: number;
      transcript_shown: boolean;
      playback_status: string;
      recorded_at: string | null;
      recording_available: boolean;
      feedback: 'unavailable' | null;
    }[] = [];
    const uploads: { number: number; bytes: number; type: string | undefined; head: string }[] = [];
    const mimes: string[] = [];
    const root = `/sessions/${session.id}/shadow/rounds`;
    await page.route('**/storage-e2e/**', async (route) => {
      const request = route.request();
      uploads.push({
        number: Number(request.url().split('/').at(-1)),
        bytes: request.postDataBuffer()?.length ?? 0,
        type: request.headers()['content-type'],
        // WebKit does not expose a Blob request body to the test, so this is empty there.
        head: (request.postDataBuffer()?.subarray(0, 12) ?? Buffer.alloc(0)).toString('latin1'),
      });
      return route.fulfill({ status: 200 });
    });
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
      if (path === `/sessions/${session.id}`)
        return route.fulfill({
          json:
            rounds.length === 3 && rounds.every((r) => r.recording_available)
              ? sessionFixture({ done: 4, passage: session.passage })
              : session,
        });
      if (path === `/sessions/${session.id}/shadow/segment`)
        return route.fulfill({ json: segment });
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
      if (path.endsWith('/recording') && request.method() === 'POST' && path.startsWith(root)) {
        const number = Number(path.split('/').at(-2));
        const body = request.postDataJSON() as { mime: string; size_bytes: number };
        expect(body.mime).toMatch(/^audio\/(webm|mp4)$/);
        mimes.push(body.mime);
        expect(body.size_bytes).toBeGreaterThan(0);
        return route.fulfill({
          json: {
            round_id: rounds[number - 1].id,
            upload: {
              url: `/storage-e2e/${number}`,
              method: 'PUT',
              headers: { 'Content-Type': body.mime },
              expires_at: '2026-10-27T10:05:00Z',
            },
          },
        });
      }
      const complete = /^\/shadow\/rounds\/(round-\d)\/complete$/.exec(path);
      if (complete && request.method() === 'POST') {
        expect(request.postDataJSON()).toEqual({ version: 3 });
        const round = rounds.find((r) => r.id === complete[1])!;
        round.recorded_at = '2026-10-27T10:00:00Z';
        round.recording_available = true;
        round.feedback = 'unavailable';
        return route.fulfill({ status: 204 });
      }
      if (/^\/shadow\/rounds\/round-\d\/recording$/.test(path))
        return route.fulfill({ contentType: 'audio/wav', body: wav() });
      if (path.startsWith(root + '/') && request.method() === 'POST') {
        const number = Number(path.split('/').at(-2));
        if (path.endsWith('/start')) {
          rounds.push({
            id: `round-${number}`,
            recording_available: false,
            feedback: null,
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
    if (variant !== 'browser default') {
      // Refuse WebM the way a Safari without WebM recording does.
      await page.addInitScript(() => {
        if (typeof MediaRecorder === 'undefined') return;
        const supported = MediaRecorder.isTypeSupported.bind(MediaRecorder);
        MediaRecorder.isTypeSupported = (type: string) => !/webm/i.test(type) && supported(type);
      });
    }
    await page.goto(`/sessions/${session.id}`);
    await skipWithoutMediaRecorder(page);
    const aacPossible = await page.evaluate(() => MediaRecorder.isTypeSupported('audio/mp4'));
    test.skip(
      variant !== 'browser default' && !aacPossible,
      'this browser cannot record AAC in MP4',
    );
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
      await expect(page.locator('audio:not([controls])')).toHaveCount(1);
      const play = page.getByRole('button', { name: `Play round ${number}`, exact: true });
      await expect(play).toBeEnabled();
      await play.focus();
      await expect(play).toBeFocused();
      await page.keyboard.press('Space');
      await expect(
        page.getByRole('status').filter({ hasText: `Round ${number} starts in 3` }),
      ).toBeVisible();
      await expect
        .poll(() =>
          page.locator('audio:not([controls])').evaluate((audio: HTMLAudioElement) => audio.paused),
        )
        .toBe(true);
      await expect(
        page.getByRole('status').filter({ hasText: 'playing at original speed' }),
      ).toBeVisible();
      await expect(page.getByRole('status')).toHaveCount(1);
      await page.locator('audio:not([controls])').evaluate((audio: HTMLAudioElement) => {
        audio.playbackRate = 1.5;
      });
      await expect
        .poll(() =>
          page
            .locator('audio:not([controls])')
            .evaluate((audio: HTMLAudioElement) => audio.playbackRate),
        )
        .toBe(1);
      await page.locator('audio:not([controls])').evaluate((audio: HTMLAudioElement) => {
        audio.currentTime = 55.1;
        audio.dispatchEvent(new Event('timeupdate'));
      });
      if (number < 3) {
        await expect(page.getByText('Playback ended.', { exact: true })).toBeVisible();
        await expect(page.getByRole('list', { name: 'Round status' })).toContainText(
          `Round ${number}: recorded`,
        );
      } else await expect(page.getByText('All 4 steps finished')).toBeVisible();
      expect(uploads.at(-1)).toMatchObject({ number });
      // WebKit gives the test no request body; the declared size_bytes is checked above.
      if (browserName !== 'webkit') expect(uploads.at(-1)!.bytes).toBeGreaterThan(0);
      expect(uploads.at(-1)!.type).toMatch(/^audio\/(webm|mp4)$/);
    }
    expect(uploads.map((u) => u.number)).toEqual([1, 2, 3]);
    // Container check: WebM starts with the EBML magic, MP4 has `ftyp` at byte 4. WebKit
    // gives the test no request body, so the declared type has to do there.
    const chromiumOrFirefox = browserName !== 'webkit';
    const expected =
      variant !== 'browser default'
        ? 'audio/mp4'
        : await page.evaluate(() =>
            MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm' : 'audio/mp4',
          );
    if (variant === 'browser default' && chromiumOrFirefox) expect(expected).toBe('audio/webm');
    expect(mimes).toEqual([expected, expected, expected]);
    expect(uploads.map((u) => u.type)).toEqual([expected, expected, expected]);
    if (chromiumOrFirefox) {
      for (const upload of uploads) {
        if (expected === 'audio/webm') expect(upload.head.startsWith('\x1aE\xdf\xa3')).toBe(true);
        else expect(upload.head.slice(4, 8)).toBe('ftyp');
      }
    }
    for (const number of [1, 2, 3]) {
      const replay = page.getByRole('region', { name: `Round ${number} replay` });
      await expect(replay.getByLabel(`Your recording of round ${number}`)).toBeVisible();
      await expect(replay.getByLabel(`Original, round ${number} segment`)).toBeVisible();
    }
    await expect(page.getByRole('button', { name: 'Start round 4' })).toHaveCount(0);
    await expect(page.getByText('Feedback unavailable.')).toBeVisible();
    await page.reload();
    await expect(page.getByText('All 4 steps finished')).toBeVisible();
    await expect(page.getByLabel('Your recording of round 3')).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      ),
    ).toBe(0);
  });
}

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

test('denied microphone permission recovers through the confirmed skip path', async ({
  page,
  browserName,
}) => {
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
  await denyMicrophone(page, browserName);
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
