import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { renderWithProviders, jsonResponse } from '../../test-utils';
import { mockRoutes } from '../session/testApi';
import { ShadowReadiness } from './ShadowReadiness';

it.each([
  ['NotAllowedError', /site settings/],
  ['NotFoundError', /Connect a microphone/],
  ['NotReadableError', /Close other apps/],
])('recovers from %s without allowing a round', async (name, advice) => {
  mockRoutes({
    'GET /auth/consent-versions': jsonResponse(200, { voice_recording: 'voice-2026-1' }),
    'GET /me/consents': jsonResponse(200, { consents: [] }),
  });
  media();
  const getUserMedia = vi.fn().mockRejectedValue(new DOMException('failure', name));
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia } });
  const ready = vi.fn();
  renderWithProviders(<ShadowReadiness onReady={ready} />);
  fireEvent.click(screen.getByRole('button', { name: 'Check microphone' }));
  await screen.findByText(advice);
  expect(ready).not.toHaveBeenCalledWith(true);
  expect(getUserMedia).toHaveBeenCalledWith({ audio: true });
  expect(screen.getByRole('button', { name: 'Check microphone' })).toBeEnabled();
});

it('shows the current legal text and requires explicit agreement', async () => {
  const { calls } = mockRoutes({
    'GET /auth/consent-versions': jsonResponse(200, { voice_recording: 'voice-2026-1' }),
    'GET /me/consents': jsonResponse(200, { consents: [] }),
    'POST /me/consents': activeConsent(),
  });
  renderWithProviders(<ShadowReadiness onReady={vi.fn()} />);
  await screen.findByText('Voice recording consent — version voice-2026-1');
  expect(screen.getByRole('button', { name: 'Agree to voice recording' })).toHaveAttribute(
    'aria-disabled',
    'true',
  );
  fireEvent.click(screen.getByRole('button', { name: 'Agree to voice recording' }));
  expect(calls.some((c) => c.method === 'POST')).toBe(false);
  fireEvent.click(screen.getByRole('checkbox', { name: /I agree/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Agree to voice recording' }));
  await vi.waitFor(() =>
    expect(
      calls.some(
        (c) => c.method === 'POST' && (c.body as { version: string }).version === 'voice-2026-1',
      ),
    ).toBe(true),
  );
  await vi.waitFor(() => expect(screen.getByText(/You agreed to this version/)).toHaveFocus());
});

it('requires a new unchecked agreement after accepting and then losing consent', async () => {
  const { ShadowRounds } = await import('./ShadowRounds');
  let held = false;
  mockRoutes({
    'GET /sessions/s/shadow/rounds': jsonResponse(200, {
      segment: { start_ms: 0, end_ms: 60000 },
      current: null,
      rounds: [],
    }),
    'GET /contents/c': jsonResponse(200, { media_url: '/audio' }),
    'GET /auth/consent-versions': jsonResponse(200, { voice_recording: 'voice-2026-1' }),
    'GET /me/consents': () => (held ? activeConsent() : jsonResponse(200, { consents: [] })),
    'POST /me/consents': () => {
      held = true;
      return activeConsent();
    },
    'POST /sessions/s/shadow/rounds/1/start': () => {
      held = false;
      return jsonResponse(403, { code: 'voice_consent_required', detail: 'Agree again.' });
    },
  });
  media();
  renderWithProviders(<ShadowRounds sessionId="s" contentId="c" />);
  fireEvent.click(await screen.findByRole('checkbox', { name: /I agree/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Agree to voice recording' }));
  await screen.findByText(/You agreed to this version/);
  fireEvent.click(screen.getByRole('button', { name: 'Check microphone' }));
  await screen.findByText('Microphone ready. Sound detected.');
  await vi.waitFor(() =>
    expect(screen.getByRole('button', { name: 'Start round 1' })).not.toHaveAttribute(
      'aria-disabled',
    ),
  );
  fireEvent.click(screen.getByRole('button', { name: 'Start round 1' }));
  expect(await screen.findByRole('checkbox', { name: /I agree/ })).not.toBeChecked();
  expect(screen.getByRole('button', { name: 'Agree to voice recording' })).toHaveAttribute(
    'aria-disabled',
    'true',
  );
});

it('links to the canonical voice consent page', async () => {
  mockRoutes({
    'GET /auth/consent-versions': jsonResponse(200, { voice_recording: 'voice-2026-1' }),
    'GET /me/consents': activeConsent(),
  });
  renderWithProviders(<ShadowReadiness onReady={vi.fn()} />);
  expect(await screen.findByRole('link', { name: 'Voice recording consent' })).toHaveAttribute(
    'href',
    '/voice-consent',
  );
});

it('consumes the explicit agreement before waiting for the grant response', async () => {
  mockRoutes({
    'GET /auth/consent-versions': jsonResponse(200, { voice_recording: 'voice-2026-1' }),
    'GET /me/consents': jsonResponse(200, { consents: [] }),
    'POST /me/consents': () => new Promise<Response>(() => {}),
  });
  renderWithProviders(<ShadowReadiness onReady={vi.fn()} />);
  const checkbox = await screen.findByRole('checkbox', { name: /I agree/ });
  fireEvent.click(checkbox);
  fireEvent.click(screen.getByRole('button', { name: 'Agree to voice recording' }));
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Agree to voice recording' })).toHaveAttribute(
      'aria-busy',
      'true',
    ),
  );
  expect(checkbox).not.toBeChecked();
});

function media(amplitude: number | (() => number) = 0.1) {
  const track = new EventTarget() as EventTarget & {
    readyState: string;
    stop: ReturnType<typeof vi.fn>;
  };
  track.readyState = 'live';
  track.stop = vi.fn();
  const stream = { getTracks: () => [track], getAudioTracks: () => [track] };
  const close = vi.fn().mockResolvedValue(undefined);
  const resume = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal(
    'AudioContext',
    class {
      createAnalyser() {
        return {
          fftSize: 32,
          getFloatTimeDomainData: (samples: Float32Array) =>
            samples.fill(typeof amplitude === 'function' ? amplitude() : amplitude),
        };
      }
      createMediaStreamSource() {
        return { connect: vi.fn() };
      }
      resume = resume;
      close = close;
    },
  );
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
  });
  return { stream, track, close, resume };
}

function activeConsent(version = 'voice-2026-1', withdrawn_at: string | null = null) {
  return jsonResponse(200, { consents: [{ kind: 'voice_recording', version, withdrawn_at }] });
}

async function checkAudibleMicrophone() {
  vi.useFakeTimers();
  fireEvent.click(screen.getByRole('button', { name: 'Check microphone' }));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1000);
  });
  vi.useRealTimers();
}

it('requires audible input and current consent, detects disconnection and releases resources', async () => {
  mockRoutes({
    'GET /auth/consent-versions': jsonResponse(200, { voice_recording: 'voice-2026-1' }),
    'GET /me/consents': activeConsent(),
  });
  const { track, close } = media();
  const ready = vi.fn();
  const view = renderWithProviders(<ShadowReadiness onReady={ready} />);
  await screen.findByText(/You agreed to this version/);
  expect(ready).not.toHaveBeenCalledWith(true);
  await checkAudibleMicrophone();
  await screen.findByText('Microphone ready. Sound detected.');
  expect(screen.getByRole('meter', { name: 'Microphone level' })).toHaveAttribute('value', '50');
  expect(ready).toHaveBeenLastCalledWith(true);
  expect(close).toHaveBeenCalled();
  act(() => {
    track.dispatchEvent(new Event('ended'));
  });
  expect(ready).toHaveBeenLastCalledWith(false);
  expect(track.stop).toHaveBeenCalled();
  view.unmount();
});

it.each([
  ['old', null],
  ['voice-2026-1', '2026-10-26'],
])('does not accept stale or withdrawn consent (%s, %s)', async (version, withdrawn) => {
  mockRoutes({
    'GET /auth/consent-versions': jsonResponse(200, { voice_recording: 'voice-2026-1' }),
    'GET /me/consents': activeConsent(version!, withdrawn),
  });
  media();
  const ready = vi.fn();
  renderWithProviders(<ShadowReadiness onReady={ready} />);
  await checkAudibleMicrophone();
  await screen.findByText('Microphone ready. Sound detected.');
  expect(ready).not.toHaveBeenCalledWith(true);
  expect(screen.getByRole('checkbox')).not.toBeChecked();
});

it('releases a late permission result after leaving the page', async () => {
  mockRoutes({});
  const { stream, track } = media();
  let resolve!: (value: unknown) => void;
  navigator.mediaDevices.getUserMedia = vi.fn().mockReturnValue(
    new Promise((r) => {
      resolve = r;
    }),
  );
  const view = renderWithProviders(<ShadowReadiness onReady={vi.fn()} />);
  fireEvent.click(screen.getByRole('button', { name: 'Check microphone' }));
  view.unmount();
  resolve(stream);
  await vi.waitFor(() => expect(track.stop).toHaveBeenCalled());
});

it('blocks silence and offers another check', async () => {
  mockRoutes({
    'GET /auth/consent-versions': jsonResponse(200, { voice_recording: 'voice-2026-1' }),
    'GET /me/consents': activeConsent(),
  });
  const { track } = media(0);
  const ready = vi.fn();
  renderWithProviders(<ShadowReadiness onReady={ready} />);
  await screen.findByText(/You agreed to this version/);
  vi.useFakeTimers();
  fireEvent.click(screen.getByRole('button', { name: 'Check microphone' }));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10100);
  });
  expect(screen.getByText(/No clear sound detected/)).toBeInTheDocument();
  expect(ready).not.toHaveBeenCalledWith(true);
  expect(track.stop).toHaveBeenCalled();
  vi.useRealTimers();
});

it('cancels a pending permission request and disposes its late stream', async () => {
  mockRoutes({});
  const { stream, track } = media();
  let resolve!: (value: unknown) => void;
  navigator.mediaDevices.getUserMedia = vi.fn().mockReturnValue(
    new Promise((r) => {
      resolve = r;
    }),
  );
  renderWithProviders(<ShadowReadiness onReady={vi.fn()} />);
  fireEvent.click(screen.getByRole('button', { name: 'Check microphone' }));
  fireEvent.click(screen.getByRole('button', { name: 'Cancel microphone check' }));
  resolve(stream);
  await vi.waitFor(() => expect(track.stop).toHaveBeenCalled());
  expect(screen.getByText(/Microphone check stopped/)).toBeInTheDocument();
});

it.each(['future-version', 'constructor'])(
  'fails closed for unavailable legal text %s',
  async (version) => {
    mockRoutes({
      'GET /auth/consent-versions': jsonResponse(200, { voice_recording: version }),
      'GET /me/consents': activeConsent(version),
    });
    media();
    const ready = vi.fn();
    renderWithProviders(<ShadowReadiness onReady={ready} />);
    fireEvent.click(screen.getByRole('button', { name: 'Check microphone' }));
    await screen.findByText('Microphone ready. Sound detected.');
    expect(screen.getByText(/current voice consent text is unavailable/)).toBeInTheDocument();
    expect(ready).not.toHaveBeenCalledWith(true);
  },
);

it('stops a checked microphone when the page is hidden', async () => {
  mockRoutes({
    'GET /auth/consent-versions': jsonResponse(200, { voice_recording: 'voice-2026-1' }),
    'GET /me/consents': activeConsent(),
  });
  const { track } = media();
  const ready = vi.fn();
  renderWithProviders(<ShadowReadiness onReady={ready} />);
  fireEvent.click(screen.getByRole('button', { name: 'Check microphone' }));
  await screen.findByText('Microphone ready. Sound detected.');
  vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);
  fireEvent(document, new Event('visibilitychange'));
  expect(track.stop).toHaveBeenCalled();
  expect(ready).toHaveBeenLastCalledWith(false);
});

it('recognizes repeated speech with pauses rather than requiring an uninterrupted tone', async () => {
  mockRoutes({
    'GET /auth/consent-versions': jsonResponse(200, { voice_recording: 'voice-2026-1' }),
    'GET /me/consents': activeConsent(),
  });
  let sample = 0;
  media(() => (++sample % 2 ? 0.1 : 0));
  renderWithProviders(<ShadowReadiness onReady={vi.fn()} />);
  fireEvent.click(screen.getByRole('button', { name: 'Check microphone' }));
  await screen.findByText('Microphone ready. Sound detected.');
});

it('returns to explicit consent when the server refuses a cached consent at start', async () => {
  const { ShadowRounds } = await import('./ShadowRounds');
  let withdrawn = false;
  mockRoutes({
    'GET /sessions/s/shadow/rounds': jsonResponse(200, {
      segment: { start_ms: 0, end_ms: 60000 },
      current: null,
      rounds: [],
    }),
    'GET /contents/c': jsonResponse(200, { media_url: '/audio' }),
    'GET /auth/consent-versions': jsonResponse(200, { voice_recording: 'voice-2026-1' }),
    'GET /me/consents': () => activeConsent('voice-2026-1', withdrawn ? 'now' : null),
    'POST /sessions/s/shadow/rounds/1/start': () => {
      withdrawn = true;
      return jsonResponse(403, {
        code: 'voice_consent_required',
        detail: 'Agree before starting.',
      });
    },
  });
  media();
  renderWithProviders(<ShadowRounds sessionId="s" contentId="c" />);
  const mic = await screen.findByRole('button', { name: 'Check microphone' });
  fireEvent.click(mic);
  await screen.findByText('Microphone ready. Sound detected.');
  await vi.waitFor(() =>
    expect(screen.getByRole('button', { name: 'Start round 1' })).not.toHaveAttribute(
      'aria-disabled',
    ),
  );
  fireEvent.click(screen.getByRole('button', { name: 'Start round 1' }));
  await screen.findByRole('checkbox', { name: /I agree/ });
  expect(screen.getByRole('button', { name: 'Start round 1' })).toHaveAttribute(
    'aria-disabled',
    'true',
  );
});

it('revokes readiness if the browser mutes the input after a successful check', async () => {
  mockRoutes({
    'GET /auth/consent-versions': jsonResponse(200, { voice_recording: 'voice-2026-1' }),
    'GET /me/consents': activeConsent(),
  });
  const { track } = media();
  const ready = vi.fn();
  renderWithProviders(<ShadowReadiness onReady={ready} />);
  fireEvent.click(screen.getByRole('button', { name: 'Check microphone' }));
  await screen.findByText('Microphone ready. Sound detected.');
  act(() => {
    track.dispatchEvent(new Event('mute'));
  });
  expect(ready).toHaveBeenLastCalledWith(false);
});

it('explains unsupported microphone APIs without enabling a round', async () => {
  mockRoutes({});
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: undefined });
  const ready = vi.fn();
  renderWithProviders(<ShadowReadiness onReady={ready} />);
  fireEvent.click(screen.getByRole('button', { name: 'Check microphone' }));
  await screen.findByText(/Microphone checking is unavailable/);
  expect(ready).not.toHaveBeenCalledWith(true);
});

it('recovers when permission resolves without a live microphone', async () => {
  mockRoutes({});
  const { track } = media();
  track.readyState = 'ended';
  const ready = vi.fn();
  renderWithProviders(<ShadowReadiness onReady={ready} />);
  fireEvent.click(screen.getByRole('button', { name: 'Check microphone' }));
  await screen.findByText(/Connect a microphone/);
  expect(track.stop).toHaveBeenCalled();
  expect(ready).not.toHaveBeenCalledWith(true);
});

it.each(['versions', 'records'])(
  'fails closed and retries a failed consent %s read',
  async (failed) => {
    let broken = true;
    mockRoutes({
      'GET /auth/consent-versions': () =>
        failed === 'versions' && broken
          ? jsonResponse(503, { code: 'unavailable', detail: 'Consent unavailable.' })
          : jsonResponse(200, { voice_recording: 'voice-2026-1' }),
      'GET /me/consents': () =>
        failed === 'records' && broken
          ? jsonResponse(503, { code: 'unavailable', detail: 'Consent unavailable.' })
          : activeConsent(),
    });
    media();
    const ready = vi.fn();
    renderWithProviders(<ShadowReadiness onReady={ready} />);
    fireEvent.click(screen.getByRole('button', { name: 'Check microphone' }));
    await screen.findByText('Microphone ready. Sound detected.');
    expect(ready).not.toHaveBeenCalledWith(true);
    broken = false;
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    await screen.findByText(/You agreed to this version/);
    await vi.waitFor(() => expect(ready).toHaveBeenLastCalledWith(true));
  },
);

it('resumes the audio context during activation before waiting for permission', async () => {
  mockRoutes({
    'GET /auth/consent-versions': jsonResponse(200, { voice_recording: 'voice-2026-1' }),
    'GET /me/consents': activeConsent(),
  });
  const { stream, resume } = media();
  let resolve!: (value: unknown) => void;
  navigator.mediaDevices.getUserMedia = vi.fn().mockReturnValue(
    new Promise((r) => {
      resolve = r;
    }),
  );
  const ready = vi.fn();
  renderWithProviders(<ShadowReadiness onReady={ready} />);
  fireEvent.click(screen.getByRole('button', { name: 'Check microphone' }));
  expect(resume).toHaveBeenCalledOnce();
  expect(ready).not.toHaveBeenCalledWith(true);
  resolve(stream);
  await screen.findByText('Microphone ready. Sound detected.');
});

it('disposes capture when audio activation resolves after cancellation', async () => {
  mockRoutes({});
  const { track, resume, close } = media();
  let resolve!: () => void;
  resume.mockReturnValue(
    new Promise<void>((done) => {
      resolve = done;
    }),
  );
  const ready = vi.fn();
  renderWithProviders(<ShadowReadiness onReady={ready} />);
  fireEvent.click(screen.getByRole('button', { name: 'Check microphone' }));
  await act(async () => {
    await Promise.resolve();
  });
  fireEvent.click(screen.getByRole('button', { name: 'Cancel microphone check' }));
  await act(async () => {
    resolve();
  });
  expect(track.stop).toHaveBeenCalled();
  expect(close).toHaveBeenCalled();
  expect(ready).not.toHaveBeenCalledWith(true);
  expect(screen.getByText(/Microphone check stopped/)).toBeInTheDocument();
});

it('shows a refused grant and lets the learner explicitly try acceptance again', async () => {
  let broken = true;
  mockRoutes({
    'GET /auth/consent-versions': jsonResponse(200, { voice_recording: 'voice-2026-1' }),
    'GET /me/consents': jsonResponse(200, { consents: [] }),
    'POST /me/consents': () =>
      broken
        ? jsonResponse(503, { code: 'unavailable', detail: 'Consent could not be saved.' })
        : activeConsent(),
  });
  renderWithProviders(<ShadowReadiness onReady={vi.fn()} />);
  fireEvent.click(await screen.findByRole('checkbox', { name: /I agree/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Agree to voice recording' }));
  await screen.findByText('Consent could not be saved.');
  expect(screen.queryByText(/You agreed to this version/)).not.toBeInTheDocument();
  broken = false;
  fireEvent.click(screen.getByRole('checkbox', { name: /I agree/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Agree to voice recording' }));
  await screen.findByText(/You agreed to this version/);
});
