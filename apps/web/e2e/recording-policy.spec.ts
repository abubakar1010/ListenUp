import { expect, test } from './test';
import { recordingSkipReason } from './recording-policy';

// NFR-COM-1: a required runner losing recording support must fail, never skip.
for (const browser of ['chromium', 'firefox', 'webkit']) {
  for (const platform of ['linux', 'darwin']) {
    if (browser === 'webkit' && platform === 'linux') continue;
    test(`${browser} on ${platform} fails without MediaRecorder`, () => {
      expect(() => recordingSkipReason(browser, platform, false, false, false)).toThrow(
        'MediaRecorder is required',
      );
    });
  }
}

test('Linux WebKit without MediaRecorder is an explicit exception', () => {
  expect(recordingSkipReason('webkit', 'linux', false, false, false)).toMatch(/Linux WebKit/);
});

test('Firefox without MP4 skips only the MP4 variant', () => {
  expect(recordingSkipReason('firefox', 'linux', true, false, false)).toBeUndefined();
  expect(recordingSkipReason('firefox', 'linux', true, false, true)).toMatch(/Firefox.*MP4/);
});

for (const browser of ['chromium', 'webkit']) {
  test(`${browser} losing MP4 support fails the MP4 variant`, () => {
    expect(() => recordingSkipReason(browser, 'darwin', true, false, true)).toThrow(
      'MP4 recording is required',
    );
  });
}

test('a capable required runner has no skip reason', () => {
  expect(recordingSkipReason('webkit', 'darwin', true, true, true)).toBeUndefined();
});
