import { renderHook } from '@testing-library/react';
import { useRoundRecorder } from './recording';

it('never starts a recorder for a round that ended while the microphone was opening', async () => {
  const track = { stop: vi.fn() };
  let open!: (stream: unknown) => void;
  const started: unknown[] = [];
  class Recorder {
    static isTypeSupported = () => true;
    state = 'inactive';
    mimeType = 'audio/webm';
    constructor() {
      started.push(this);
    }
    addEventListener() {}
    start() {
      this.state = 'recording';
    }
    stop() {}
  }
  vi.stubGlobal('MediaRecorder', Recorder);
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: {
      getUserMedia: () =>
        new Promise((resolve) => {
          open = resolve;
        }),
    },
  });
  const { result } = renderHook(() => useRoundRecorder());
  const begun = result.current.begin();
  expect(await result.current.finish()).toBeNull();
  open({ getTracks: () => [track] });
  expect(await begun).toBe('cancelled');
  expect(started).toHaveLength(0);
  expect(track.stop).toHaveBeenCalled();
  vi.unstubAllGlobals();
});
