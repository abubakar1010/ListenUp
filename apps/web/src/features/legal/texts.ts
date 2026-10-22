import privacy20261 from '../../../../../docs/legal/privacy-2026-1.md?raw';
import terms20261 from '../../../../../docs/legal/terms-2026-1.md?raw';
import voice20261 from '../../../../../docs/legal/voice-2026-1.md?raw';

/**
 * Every published version of each legal text, by its label (#103, ADR 0051). The files
 * in docs/legal are the source; the API's LISTENUP_*_VERSION names the current label.
 */
export const TEXTS: Record<'terms' | 'privacy' | 'voice_recording', Record<string, string>> = {
  terms: { 'terms-2026-1': terms20261 },
  privacy: { 'privacy-2026-1': privacy20261 },
  voice_recording: { 'voice-2026-1': voice20261 },
};
