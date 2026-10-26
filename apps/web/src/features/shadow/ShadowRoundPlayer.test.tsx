import { act, fireEvent, screen } from '@testing-library/react';
import { renderWithProviders } from '../../test-utils';
import { ShadowRoundPlayer } from './ShadowRoundPlayer';

beforeEach(() => {
  vi.useFakeTimers();
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue();
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

it('counts in, enforces 1x, and reports only bounded playback ending', async () => {
  const ended = vi.fn();
  renderWithProviders(
    <ShadowRoundPlayer src="/audio" startMs={10000} endMs={70000} number={1} onEnded={ended} />,
  );
  const audio = document.querySelector('audio')!;
  fireEvent.loadedMetadata(audio);
  const button = screen.getByRole('button', { name: 'Play round 1' });
  button.focus();
  expect(button).toHaveFocus();
  fireEvent.click(button);
  expect(screen.getByRole('status')).toHaveTextContent('3');
  await act(async () => {
    vi.advanceTimersByTime(3000);
  });
  expect(audio.play).toHaveBeenCalledTimes(1);
  expect(audio.currentTime).toBe(10);
  audio.playbackRate = 1.5;
  fireEvent.rateChange(audio);
  expect(audio.playbackRate).toBe(1);
  expect(audio.defaultPlaybackRate).toBe(1);
  expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  audio.currentTime = 70.5;
  fireEvent.timeUpdate(audio);
  expect(audio.currentTime).toBe(70);
  expect(ended).toHaveBeenCalledTimes(1);
  fireEvent.ended(audio);
  expect(ended).toHaveBeenCalledTimes(1);
});

it('cancels the count-in and restarts an interrupted round without ending it', async () => {
  const ended = vi.fn();
  const view = renderWithProviders(
    <ShadowRoundPlayer src="/audio" startMs={10000} endMs={70000} number={2} onEnded={ended} />,
  );
  const audio = document.querySelector('audio')!;
  fireEvent.loadedMetadata(audio);
  fireEvent.click(screen.getByRole('button', { name: 'Play round 2' }));
  fireEvent.click(screen.getByRole('button', { name: 'Stop round 2' }));
  await act(async () => {
    vi.advanceTimersByTime(3000);
  });
  expect(audio.play).not.toHaveBeenCalled();
  expect(ended).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Play round 2' }));
  await act(async () => {
    vi.advanceTimersByTime(3000);
  });
  fireEvent.pause(audio);
  expect(screen.getByRole('status')).toHaveTextContent('interrupted');
  view.unmount();
  expect(ended).not.toHaveBeenCalled();
});

it('recovers from autoplay refusal with a direct keyboard-operable play action', async () => {
  vi.mocked(HTMLMediaElement.prototype.play).mockRejectedValueOnce(new Error('blocked'));
  renderWithProviders(<ShadowRoundPlayer src="/audio" startMs={10000} endMs={70000} number={3} />);
  const audio = document.querySelector('audio')!;
  expect(screen.getByRole('button', { name: 'Play round 3' })).toBeDisabled();
  fireEvent.loadedMetadata(audio);
  fireEvent.click(screen.getByRole('button', { name: 'Play round 3' }));
  await act(async () => {
    vi.advanceTimersByTime(3000);
  });
  expect(screen.getByRole('status')).toHaveTextContent('Playback was blocked');
  fireEvent.click(screen.getByRole('button', { name: 'Play now' }));
  expect(audio.play).toHaveBeenCalledTimes(2);
});

it('stops on hidden pages or media errors and never reports an ended round', async () => {
  const ended = vi.fn();
  renderWithProviders(
    <ShadowRoundPlayer src="/audio" startMs={10000} endMs={70000} number={2} onEnded={ended} />,
  );
  const audio = document.querySelector('audio')!;
  fireEvent.loadedMetadata(audio);
  fireEvent.click(screen.getByRole('button', { name: 'Play round 2' }));
  vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);
  fireEvent(document, new Event('visibilitychange'));
  await act(async () => {
    vi.advanceTimersByTime(3000);
  });
  expect(audio.play).not.toHaveBeenCalled();
  fireEvent.ended(audio);
  expect(ended).not.toHaveBeenCalled();
  fireEvent.error(audio);
  expect(screen.getByRole('status')).toHaveTextContent('Audio unavailable');
  expect(screen.getByRole('button', { name: 'Play round 2' })).toBeDisabled();
});

it('handles the native pause before ended at the segment boundary', async () => {
  const ended = vi.fn();
  renderWithProviders(
    <ShadowRoundPlayer src="/audio" startMs={0} endMs={45000} number={1} onEnded={ended} />,
  );
  const audio = document.querySelector('audio')!;
  fireEvent.loadedMetadata(audio);
  fireEvent.click(screen.getByRole('button', { name: 'Play round 1' }));
  await act(async () => {
    vi.advanceTimersByTime(3000);
  });
  audio.currentTime = 45;
  fireEvent.pause(audio);
  fireEvent.ended(audio);
  expect(ended).toHaveBeenCalledTimes(1);
});

it('does not advance when media ends before the selected segment boundary', async () => {
  const ended = vi.fn();
  renderWithProviders(
    <ShadowRoundPlayer src="/audio" startMs={10000} endMs={70000} number={1} onEnded={ended} />,
  );
  const audio = document.querySelector('audio')!;
  fireEvent.loadedMetadata(audio);
  fireEvent.click(screen.getByRole('button', { name: 'Play round 1' }));
  await act(async () => {
    vi.advanceTimersByTime(3000);
  });
  audio.currentTime = 20;
  fireEvent.ended(audio);
  expect(ended).not.toHaveBeenCalled();
  expect(screen.getByRole('status')).toHaveTextContent('Audio unavailable');
});

it('does not rewrite an already-correct media rate on ratechange', () => {
  renderWithProviders(<ShadowRoundPlayer src="/audio" startMs={10000} endMs={70000} number={1} />);
  const audio = document.querySelector('audio')!;
  fireEvent.loadedMetadata(audio);
  const rate = vi.spyOn(audio, 'playbackRate', 'set');
  const defaultRate = vi.spyOn(audio, 'defaultPlaybackRate', 'set');
  fireEvent.rateChange(audio);
  expect(rate).not.toHaveBeenCalled();
  expect(defaultRate).not.toHaveBeenCalled();
});
