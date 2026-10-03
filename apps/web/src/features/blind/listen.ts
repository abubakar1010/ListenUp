import { ApiError } from '../../api/client';
import type {
  BlindAttempt,
  ClientVoidReason,
  HeartbeatIn,
  HeartbeatOut,
  StartedAttempt,
} from './api';

/**
 * Blind's control policy (FR-BL-1, UI-3) and its side of the heartbeat protocol (#63,
 * ADR 0024). The learner gets Start and volume only: the audio element has no
 * controls, cannot be focused, and every seek, pause or speed change that this class
 * did not make itself is either undone or ends the attempt. The server judges every
 * beat; this class reports honestly what the player did:
 *
 * - every 5 s a beat with the position, the state and the time the audio waited
 *   (loading, waiting for data, the resume's wait and count);
 * - when beats stop getting through for 10 s, it stops playback and waits for the
 *   connection, then reports the stop as a network interruption;
 * - when the device pauses the audio, it reports a device interruption;
 * - the server answers `resume` once (D13): the player goes back to the point it
 *   names, waits until the audio is ready, counts 3 s and carries on by itself (D18);
 * - a seek it did not make is reported as `seek`, and ends the attempt.
 */

/** The parts of HTMLMediaElement the controller uses, so tests can pass a fake. */
export interface MediaLike extends EventTarget {
  src: string;
  preload: string;
  currentTime: number;
  playbackRate: number;
  readonly paused: boolean;
  readonly readyState: number;
  play(): Promise<void>;
  pause(): void;
}

export interface BlindApi {
  heartbeat(attemptId: string, beat: HeartbeatIn): Promise<HeartbeatOut>;
  void(attemptId: string, reason: ClientVoidReason, keepalive?: boolean): Promise<BlindAttempt>;
}

export type Phase =
  | { kind: 'loading' }
  | { kind: 'playing' }
  | { kind: 'waiting'; cause: 'network' | 'device'; stopMs: number }
  | { kind: 'resuming'; fromMs: number; secondsLeft: number | null }
  | { kind: 'ended' }
  | { kind: 'stopped'; attempt: BlindAttempt }
  | { kind: 'failed'; error: unknown };

export interface ListenSnapshot {
  phase: Phase;
  positionMs: number;
  /** Where the one resume was used, once it was. */
  resumeStopMs: number | null;
  /** The device pause that used the resume, for the "carried on" note. */
  devicePauseMs: number | null;
}

const HAVE_FUTURE_DATA = 3;
/** Beats that fail for this long mean the connection is gone: stop and wait. */
const STALL_AFTER_MS = 10_000;
const RETRY_MS = 2_000;
const PLAY_RETRY_MS = 1_000;

export class BlindListen {
  private snapshot: ListenSnapshot;
  private readonly listeners = new Set<() => void>();
  private readonly start: number;
  private readonly end: number;
  private readonly interval: number;
  private readonly resumeDelay: number;
  private ownSeek = false;
  private ownPause = false;
  private waitingSince: number | null;
  private waitedMs = 0;
  private lastBeatOkAt: number;
  private beatTimer: ReturnType<typeof setInterval> | undefined;
  private retryTimer: ReturnType<typeof setTimeout> | undefined;
  private countdownTimer: ReturnType<typeof setTimeout> | undefined;
  private inFlight = false;
  private disposed = false;
  private left = false;
  private deviceStopAt: number | null = null;
  private readonly cleanups: (() => void)[] = [];

  constructor(
    private readonly media: MediaLike,
    private readonly started: StartedAttempt,
    private readonly server: BlindApi,
    private readonly now: () => number = () => Date.now(),
  ) {
    this.start = started.attempt.passage_start_ms;
    this.end = started.attempt.passage_end_ms;
    this.interval = started.heartbeat_interval_ms;
    this.resumeDelay = started.resume_delay_ms;
    this.waitingSince = now();
    this.lastBeatOkAt = now();
    this.snapshot = {
      phase: { kind: 'loading' },
      positionMs: this.start,
      resumeStopMs: null,
      devicePauseMs: null,
    };
  }

  get attemptId(): string {
    return this.started.attempt.id;
  }

  getSnapshot = (): ListenSnapshot => this.snapshot;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  /** Load the whole passage and play it: called from the Start button's click. */
  begin(): void {
    const media = this.media;
    this.on('loadedmetadata', () => this.seekTo(this.start));
    this.on('canplay', () => {
      if (this.snapshot.phase.kind === 'loading') void this.playNow();
      if (this.snapshot.phase.kind === 'resuming') this.startCountdown();
    });
    this.on('playing', () => this.onPlaying());
    this.on('waiting', () => this.startWaiting());
    this.on('timeupdate', () => this.onTimeUpdate());
    this.on('pause', () => this.onPause());
    this.on('seeking', () => this.onSeeking());
    this.on('ratechange', () => {
      if (media.playbackRate !== 1) media.playbackRate = 1; // speed is not a Blind control
    });
    this.on('error', () => {
      if (this.snapshot.phase.kind === 'playing') this.stall('network');
    });
    media.preload = 'auto';
    media.src = this.started.media_url;
    this.beatTimer = setInterval(() => void this.beat(), this.interval);
  }

  /** Skip the rest of the 3 s count ("Carry on now", final UI D07). */
  carryOnNow(): void {
    if (this.snapshot.phase.kind === 'resuming' && this.snapshot.phase.secondsLeft !== null) {
      clearTimeout(this.countdownTimer);
      void this.playNow();
    }
  }

  /** The listen is under way: leaving or reloading now ends the attempt. */
  get inProgress(): boolean {
    if (this.left) return false;
    const kind = this.snapshot.phase.kind;
    return kind !== 'ended' && kind !== 'stopped' && kind !== 'failed';
  }

  /** The learner leaves: report it, keeping the request alive while the page unloads. */
  leave(reason: ClientVoidReason = 'left_page'): void {
    if (this.disposed || !this.inProgress) return;
    this.left = true;
    this.stop();
    // If the page comes back (the back-forward cache), it shows how the attempt ended.
    void this.server
      .void(this.attemptId, reason, true)
      .then((attempt) => this.set({ phase: { kind: 'stopped', attempt } }))
      .catch((error: unknown) => this.set({ phase: { kind: 'failed', error } }));
  }

  /** Stop timers and listeners; the audio stops too. */
  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.stop();
    for (const cleanup of this.cleanups.splice(0)) cleanup();
  }

  private stop(): void {
    clearInterval(this.beatTimer);
    clearTimeout(this.retryTimer);
    clearTimeout(this.countdownTimer);
    this.pauseOwn();
  }

  private on(type: string, handler: () => void): void {
    this.media.addEventListener(type, handler);
    this.cleanups.push(() => this.media.removeEventListener(type, handler));
  }

  private set(change: Partial<ListenSnapshot>): void {
    this.snapshot = { ...this.snapshot, ...change };
    for (const listener of this.listeners) listener();
  }

  private position(): number {
    return Math.round(this.media.currentTime * 1000);
  }

  private seekTo(ms: number): void {
    this.ownSeek = true;
    this.media.currentTime = ms / 1000;
  }

  private pauseOwn(): void {
    if (this.media.paused) return;
    // The 'pause' event comes later, as a task; onPause clears the flag.
    this.ownPause = true;
    this.media.pause();
  }

  private startWaiting(): void {
    this.waitingSince ??= this.now();
  }

  private stopWaiting(): void {
    if (this.waitingSince !== null) {
      this.waitedMs += this.now() - this.waitingSince;
      this.waitingSince = null;
    }
  }

  private waited(): number {
    const open = this.waitingSince === null ? 0 : this.now() - this.waitingSince;
    return Math.max(0, Math.round(this.waitedMs + open));
  }

  private async playNow(): Promise<void> {
    try {
      await this.media.play();
    } catch {
      // The device still holds the audio: try again shortly; the server's limits apply.
      if (this.inProgress) this.retryTimer = setTimeout(() => void this.playNow(), PLAY_RETRY_MS);
    }
  }

  private onPlaying(): void {
    this.stopWaiting();
    const phase = this.snapshot.phase;
    if (phase.kind === 'loading' || phase.kind === 'resuming') {
      this.set({
        phase: { kind: 'playing' },
        devicePauseMs:
          this.deviceStopAt === null ? this.snapshot.devicePauseMs : this.now() - this.deviceStopAt,
      });
      this.deviceStopAt = null;
    }
  }

  private onTimeUpdate(): void {
    if (this.ownSeek) return;
    const position = Math.min(this.position(), this.end);
    if (this.snapshot.phase.kind === 'playing') {
      this.set({ positionMs: position });
      if (position >= this.end) this.finish();
    }
  }

  private onPause(): void {
    if (this.ownPause) {
      this.ownPause = false;
      return;
    }
    if (this.snapshot.phase.kind !== 'playing') return;
    // Not ours: the device or the OS paused the audio (headphones, a call).
    this.deviceStopAt = this.now();
    this.set({ phase: { kind: 'waiting', cause: 'device', stopMs: this.position() } });
    void this.beat();
  }

  private onSeeking(): void {
    if (this.ownSeek) {
      this.ownSeek = false;
      return;
    }
    if (!this.inProgress) return;
    this.stop();
    void this.server
      .void(this.attemptId, 'seek')
      .then((attempt) => this.set({ phase: { kind: 'stopped', attempt } }))
      .catch((error: unknown) => this.set({ phase: { kind: 'failed', error } }));
  }

  private finish(): void {
    this.pauseOwn();
    this.set({ phase: { kind: 'ended' }, positionMs: this.end });
    clearInterval(this.beatTimer);
    void this.beat(true);
  }

  private stall(cause: 'network' | 'device'): void {
    const stopMs = this.position();
    this.pauseOwn();
    this.startWaiting();
    this.set({ phase: { kind: 'waiting', cause, stopMs } });
  }

  private state(): HeartbeatIn['state'] {
    switch (this.snapshot.phase.kind) {
      case 'playing':
        return this.waitingSince === null ? 'playing' : 'buffering';
      case 'waiting':
        return 'interrupted';
      case 'resuming':
        return 'resuming';
      case 'ended':
        return 'ended';
      default:
        return 'buffering';
    }
  }

  private async beat(final = false): Promise<void> {
    if (this.inFlight || (!this.inProgress && !final)) return;
    const phase = this.snapshot.phase;
    const body: HeartbeatIn = {
      position_ms: phase.kind === 'waiting' ? phase.stopMs : Math.min(this.position(), this.end),
      state: this.state(),
      visible: document.visibilityState !== 'hidden',
      buffering_ms: this.waited(),
      interruption_ms: 0,
    };
    if (phase.kind === 'waiting') {
      body.interruption = phase.cause;
      if (phase.cause === 'device' && this.deviceStopAt !== null) {
        body.interruption_ms = this.now() - this.deviceStopAt;
      }
    }
    this.inFlight = true;
    try {
      const answer = await this.server.heartbeat(this.attemptId, body);
      this.lastBeatOkAt = this.now();
      this.waitedMs = 0;
      if (this.waitingSince !== null) this.waitingSince = this.now();
      this.handle(answer);
    } catch (error) {
      this.beatFailed(error);
    } finally {
      this.inFlight = false;
    }
  }

  private handle(answer: HeartbeatOut): void {
    if (answer.action === 'stop') {
      if (this.snapshot.phase.kind === 'ended' && answer.attempt.status === 'active') return;
      this.stop();
      this.set({ phase: { kind: 'stopped', attempt: answer.attempt } });
    } else if (answer.action === 'resume' && answer.resume_from_ms !== null) {
      this.resume(answer.resume_from_ms, answer.attempt.resume_stop_ms);
    }
  }

  private beatFailed(error: unknown): void {
    if (error instanceof ApiError && error.problem.status < 500) {
      // Refused for good (the attempt is gone): nothing to carry on with.
      this.stop();
      this.set({ phase: { kind: 'failed', error } });
      return;
    }
    const phase = this.snapshot.phase.kind;
    if (phase === 'playing' && this.now() - this.lastBeatOkAt >= STALL_AFTER_MS) {
      this.stall('network');
    }
    if (this.snapshot.phase.kind === 'waiting') {
      clearTimeout(this.retryTimer);
      this.retryTimer = setTimeout(() => void this.beat(), RETRY_MS);
    }
  }

  /** The one resume (D18): back to `fromMs`, wait for the audio, count 3 s, play. */
  private resume(fromMs: number, stopMs: number | null): void {
    clearTimeout(this.retryTimer);
    this.pauseOwn();
    this.startWaiting();
    this.set({
      phase: { kind: 'resuming', fromMs, secondsLeft: null },
      positionMs: fromMs,
      resumeStopMs: stopMs,
    });
    this.seekTo(fromMs);
    if (this.media.readyState >= HAVE_FUTURE_DATA) this.startCountdown();
  }

  private startCountdown(): void {
    const phase = this.snapshot.phase;
    if (phase.kind !== 'resuming' || phase.secondsLeft !== null) return;
    const tick = (left: number) => {
      if (left === 0) {
        void this.playNow();
        return;
      }
      this.set({ phase: { ...phase, secondsLeft: left } });
      this.countdownTimer = setTimeout(() => tick(left - 1), this.resumeDelay / 3);
    };
    tick(3);
  }
}
