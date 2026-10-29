import { TEXTS } from './texts';

test('retention revisions describe expiry while preserving previously accepted texts', () => {
  expect(TEXTS.privacy['privacy-2026-2']).toContain('Automatic recording expiry runs daily');
  expect(TEXTS.voice_recording['voice-2026-2']).toContain('Automatic recording expiry runs daily');
  expect(TEXTS.privacy['privacy-2026-1']).toContain('automatic deletion is not implemented yet');
  expect(TEXTS.voice_recording['voice-2026-1']).toContain(
    'Recordings are currently stored without',
  );
});
