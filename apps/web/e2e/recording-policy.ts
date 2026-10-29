/** Known runner exceptions only; losing a required capability is a failure (#99). */
export function recordingSkipReason(
  browserName: string,
  platform: string,
  recorderPresent: boolean,
  mp4Supported: boolean,
  mp4Required: boolean,
): string | undefined {
  if (!recorderPresent) {
    if (browserName === 'webkit' && platform === 'linux')
      return 'Playwright Linux WebKit ships without MediaRecorder; recording runs on macOS';
    throw new Error(`MediaRecorder is required on ${browserName}/${platform}`);
  }
  if (mp4Required && !mp4Supported) {
    if (browserName === 'firefox') return 'Firefox cannot record AAC in MP4';
    throw new Error(`MP4 recording is required on ${browserName}/${platform}`);
  }
}
