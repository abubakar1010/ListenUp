import type { QueryClient, QueryKey } from '@tanstack/react-query';

import { ME_KEY } from '../auth/useMe';
import type { LiveEvent } from '../events/useLiveEvents';
import { DELETE_ACCOUNT_KEY } from '../features/account/deletionApi';
import { EXPORTS_KEY } from '../features/account/exportApi';
import { BLIND_KEY } from '../features/blind/api';
import { CONTENTS_KEY, contentKey } from '../features/content/useContent';
import { DICTATION_RESULT_KEY } from '../features/dictation/api';
import { LIBRARY_KEY, UPLOAD_USAGE_KEY } from '../features/library/useLibrary';

const NO_KEYS: readonly QueryKey[] = [];

export const PENDING_KEYS: readonly QueryKey[] = [LIBRARY_KEY, CONTENTS_KEY, DICTATION_RESULT_KEY];

/**
 * Which cached queries each live event makes stale (ADR 0016). Feature stories add their
 * mappings here, for example `content.ready` to the content item and the library list.
 */
export function queryKeysForEvent(event: LiveEvent, queryClient: QueryClient): readonly QueryKey[] {
  switch (event.type) {
    case 'content.ready':
      // A converted clip also changes storage use and today's new audio.
      return [LIBRARY_KEY, contentKey(event.resourceId), UPLOAD_USAGE_KEY];
    case 'job.progress':
      return [LIBRARY_KEY, contentKey(event.resourceId)];
    case 'dictation.scored':
      // The event names the attempt only; refresh every Dictation result shown (ADR 0042).
      return [DICTATION_RESULT_KEY];
    case 'attempt.voided':
      // The event names the attempt only; refresh every Blind step shown (ADR 0024).
      return [BLIND_KEY];
    case 'export.ready':
      // A data export finished: ready to download, or failed (ADR 0030).
      return [EXPORTS_KEY];
    case 'account.disabled':
      // The account was deleted in another tab or device (ADR 0029): refetching the
      // learner finds nobody signed in, and the guard goes to sign in. The tab that is
      // deleting goes to the "account deleted" page itself; refetching here could send
      // it to sign in first.
      if (queryClient.isMutating({ mutationKey: DELETE_ACCOUNT_KEY }) > 0) return NO_KEYS;
      return [ME_KEY];
    default:
      return NO_KEYS;
  }
}
