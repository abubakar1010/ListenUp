import { ApiError } from '../../api/client';
import type { HeartbeatIn, HeartbeatOut, StartedAttempt } from './api';
import { attemptFixture } from './fixtures';
import { BlindListen, type BlindApi, type MediaLike } from './listen';

const START = 130_000;
const END = 280_000;

/** A media element that plays only when told to, and fires the events a browser would. */
class FakeMedia extends EventTarget implements MediaLike {
  src = '';
  preload = '';
  playbackRate = 1;
  paused = true;
  readyState = 4;
  blockPlay = false;
  private time = 0;

  get currentTime() {
    return this.time;
  }

  set currentTime(seconds: number) {
    this.time = seconds;
    this.fire('seeking');
    this.fire('timeupdate');
  }

  play = vi.fn(async () => {
    if (this.blockPlay) throw new DOMException('blocked', 'NotAllowedError');
    this.paused = false;
    this.fire('playing');
  });

  pause() {
    if (this.paused) return;
    this.paused = true;
    this.fire('pause');
  }

  /** Playback moves on by `ms`, as the browser's own clock would move it. */
  progress(ms: number) {
    this.time += ms / 1000;
    this.fire('timeupdate');
  }

  fire(type: string) {
    this.dispatchEvent(new Event(type));
  }
}

const STARTED: StartedAttempt = {
  attempt: attemptFixture(),
  media_url: '/api/v1/blind/attempts/attempt-1/media/token',
  heartbeat_interval_ms: 5_000,
  resume_delay_ms: 3_000,
};

function answer(overrides: Partial<HeartbeatOut> = {}): HeartbeatOut {
  return {
    action: 'continue',
    attempt: attemptFixture(),
    resume_from_ms: null,
    resume_delay_ms: 3_000,
    ...overrides,
  };
}

function setup(heartbeat?: (beat: HeartbeatIn) => Promise<HeartbeatOut>) {
  const media = new FakeMedia();
  const beats: HeartbeatIn[] = [];
  const server = {
    heartbeat: vi.fn(async (_id: string, beat: HeartbeatIn) => {
      beats.push(beat);
      return heartbeat ? heartbeat(beat) : answer();
    }),
    void: vi.fn(async () => attemptFixture({ status: 'voided', void_reason: 'seek' })),
  } satisfies BlindApi;
  const listen = new BlindListen(media, STARTED, server);
  return { media, beats, server, listen };
}

/** Load and start: metadata, the seek to the passage, ready, playing. */
async function started(media: FakeMedia, listen: BlindListen) {
  listen.begin();
  await vi.advanceTimersByTimeAsync(600); // loading takes 0.6 s
  media.fire('loadedmetadata');
  media.fire('canplay');
  await vi.advanceTimersByTimeAsync(0);
}

beforeEach(() => vi.useFakeTimers({ now: new Date('2026-10-03T12:00:00Z') }));
afterEach(() => vi.useRealTimers());

test('the whole passage loads, plays from its start and beats every 5 s', async () => {
  const { media, beats, listen } = setup();
  await started(media, listen);

  expect(media.preload).toBe('auto');
  expect(media.src).toBe(STARTED.media_url);
  expect(media.currentTime).toBe(START / 1000);
  expect(listen.getSnapshot().phase.kind).toBe('playing');

  media.progress(4_400);
  await vi.advanceTimersByTimeAsync(4_400);

  expect(beats).toEqual([
    {
      position_ms: START + 4_400,
      state: 'playing',
      visible: true,
      buffering_ms: 600,
      interruption_ms: 0,
    },
  ]);
  expect(listen.getSnapshot().positionMs).toBe(START + 4_400);
});

test('a seek the player did not make ends the attempt', async () => {
  const { media, server, listen } = setup();
  await started(media, listen);

  media.currentTime = 200; // the browser's own controls, or a script
  await vi.advanceTimersByTimeAsync(0);

  expect(server.void).toHaveBeenCalledWith('attempt-1', 'seek');
  expect(listen.getSnapshot().phase.kind).toBe('stopped');
  expect(media.paused).toBe(true);
});

test('a speed change is undone', async () => {
  const { media, listen } = setup();
  await started(media, listen);

  media.playbackRate = 2;
  media.fire('ratechange');

  expect(media.playbackRate).toBe(1);
});

test('the end of the passage stops playback and sends the last beat', async () => {
  const { media, beats, listen } = setup();
  await started(media, listen);

  media.progress(END - START + 200);
  await vi.advanceTimersByTimeAsync(0);

  expect(media.paused).toBe(true);
  expect(listen.getSnapshot().phase.kind).toBe('ended');
  expect(beats.at(-1)).toMatchObject({ position_ms: END, state: 'ended' });
  expect(listen.inProgress).toBe(false);
});

test('the last beat waits for a slow beat in flight instead of being dropped', async () => {
  let release: () => void = () => {};
  let hang = false;
  const { media, beats, listen } = setup(async () => {
    if (hang) {
      hang = false;
      await new Promise<void>((resolve) => (release = resolve));
    }
    return answer();
  });
  await started(media, listen);

  hang = true;
  media.progress(5_000);
  await vi.advanceTimersByTimeAsync(5_000); // a regular beat goes out and hangs
  media.progress(END - START);
  await vi.advanceTimersByTimeAsync(0);
  expect(beats.at(-1)?.state).toBe('playing');

  release();
  await vi.advanceTimersByTimeAsync(0);
  expect(beats.at(-1)).toMatchObject({ position_ms: END, state: 'ended' });
});

test('the last beat is sent again after a network failure', async () => {
  let failures = 1;
  const { media, beats, listen } = setup(async (beat) => {
    if (beat.state === 'ended' && failures > 0) {
      failures -= 1;
      throw new TypeError('network down');
    }
    return answer();
  });
  await started(media, listen);

  media.progress(END - START + 200);
  await vi.advanceTimersByTimeAsync(0);
  const sent = beats.filter((beat) => beat.state === 'ended').length;
  await vi.advanceTimersByTimeAsync(10_000);

  expect(beats.filter((beat) => beat.state === 'ended').length).toBe(sent + 1);
  expect(listen.getSnapshot().phase.kind).toBe('ended');
});

test('a stop from the server ends the listen with its reason', async () => {
  const voided = attemptFixture({ status: 'voided', void_reason: 'too_fast' });
  const { media, listen } = setup(async () => answer({ action: 'stop', attempt: voided }));
  await started(media, listen);

  await vi.advanceTimersByTimeAsync(5_000);

  expect(listen.getSnapshot().phase).toEqual({ kind: 'stopped', attempt: voided });
  expect(media.paused).toBe(true);
});

test('a network stall stops, waits, then resumes once 3 s before the stop', async () => {
  let online = true;
  const { media, beats, listen } = setup(async (beat) => {
    if (!online) throw new TypeError('Failed to fetch');
    if (beat.state === 'interrupted') {
      return answer({
        action: 'resume',
        resume_from_ms: beat.position_ms - 3_000,
        attempt: attemptFixture({ resume_count: 1, resume_stop_ms: beat.position_ms }),
      });
    }
    return answer();
  });
  await started(media, listen);
  media.progress(5_000);
  await vi.advanceTimersByTimeAsync(5_000); // beat 1 gets through
  online = false;
  media.progress(10_000);
  await vi.advanceTimersByTimeAsync(10_000); // beats 2 and 3 fail: 10 s without contact

  expect(listen.getSnapshot().phase).toEqual({
    kind: 'waiting',
    cause: 'network',
    stopMs: START + 15_000,
  });
  expect(media.paused).toBe(true);

  online = true;
  await vi.advanceTimersByTimeAsync(2_000); // the retry gets through

  expect(beats.at(-1)).toMatchObject({
    state: 'interrupted',
    interruption: 'network',
    position_ms: START + 15_000,
  });
  expect(media.currentTime).toBe((START + 12_000) / 1000);
  expect(listen.getSnapshot()).toMatchObject({
    phase: { kind: 'resuming', fromMs: START + 12_000, secondsLeft: 3 },
    resumeStopMs: START + 15_000,
  });
  await vi.advanceTimersByTimeAsync(1_000);
  expect(listen.getSnapshot().phase).toMatchObject({ secondsLeft: 2 });
  expect(media.paused).toBe(true);
  await vi.advanceTimersByTimeAsync(2_000);

  expect(media.paused).toBe(false);
  expect(listen.getSnapshot().phase.kind).toBe('playing');
});

test('"Carry on now" skips the rest of the count', async () => {
  const { media, listen } = setup(async (beat) =>
    beat.state === 'interrupted'
      ? answer({ action: 'resume', resume_from_ms: START + 2_000 })
      : answer(),
  );
  await started(media, listen);
  media.progress(5_000);
  media.pause(); // the device paused the audio
  await vi.advanceTimersByTimeAsync(0);

  listen.carryOnNow();
  await vi.advanceTimersByTimeAsync(0);

  expect(media.paused).toBe(false);
  expect(listen.getSnapshot().phase.kind).toBe('playing');
});

test('a device pause is reported as an interruption with its length', async () => {
  const { media, beats, listen } = setup(async () => answer({ action: 'continue' }));
  await started(media, listen);
  media.progress(3_000);

  media.pause();
  await vi.advanceTimersByTimeAsync(0);

  expect(beats.at(-1)).toMatchObject({
    state: 'interrupted',
    interruption: 'device',
    position_ms: START + 3_000,
    interruption_ms: 0,
  });
});

test('leaving reports left_page with a request that outlives the page', async () => {
  const { media, server, listen } = setup();
  await started(media, listen);

  listen.leave();

  expect(server.void).toHaveBeenCalledWith('attempt-1', 'left_page', true);
  expect(media.paused).toBe(true);
  expect(listen.inProgress).toBe(false);
  await vi.advanceTimersByTimeAsync(0);
  expect(listen.getSnapshot().phase.kind).toBe('stopped');
});

test('leaving after the end reports nothing', async () => {
  const { media, server, listen } = setup();
  await started(media, listen);
  media.progress(150_000);
  await vi.advanceTimersByTimeAsync(0);

  listen.leave();

  expect(server.void).not.toHaveBeenCalled();
});

test('a beat refused for good ends the listen', async () => {
  const gone = new ApiError({
    type: '/problems/attempt_not_found',
    title: '',
    status: 404,
    detail: 'This attempt was not found.',
    code: 'attempt_not_found',
  });
  const { media, listen } = setup(async () => {
    throw gone;
  });
  await started(media, listen);

  await vi.advanceTimersByTimeAsync(5_000);

  expect(listen.getSnapshot().phase).toEqual({ kind: 'failed', error: gone });
});
