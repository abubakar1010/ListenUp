import { act } from '@testing-library/react';
import { vi } from 'vitest';

import { RequireAuth } from '../../app/guards';
import { useLiveEvents } from '../../events/useLiveEvents';
import { LEARNER, renderWithProviders } from '../../test-utils';
import { REVIEW_KEY, transcriptKey } from './api';

vi.mock('../../auth/useMe', () => ({ ME_KEY: ['me'], useMe: () => ({ data: LEARNER }) }));
vi.mock('../../events/useLiveEvents', () => ({ useLiveEvents: vi.fn(() => 'off') }));

test.each(['transcript.ready', 'transcript.failed'] as const)(
  '%s invalidates only the named session transcript and reconnects cover review queries',
  (type) => {
    renderWithProviders(<RequireAuth />);
    const options = vi.mocked(useLiveEvents).mock.calls.at(-1)![0];
    let keys;
    act(() => {
      keys = options.keysFor({ id: 'event-57', type, resourceId: 'session-57' });
    });
    expect(keys).toEqual([transcriptKey('session-57')]);
    expect(options.pendingKeys).toContainEqual(REVIEW_KEY);
  },
);
