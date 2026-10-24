import { QueryClient } from '@tanstack/react-query';

import { ME_KEY } from '../auth/useMe';
import type { LiveEvent, LiveEventType } from '../events/useLiveEvents';
import { DELETE_ACCOUNT_KEY } from '../features/account/deletionApi';
import { EXPORTS_KEY } from '../features/account/exportApi';
import { BLIND_KEY } from '../features/blind/api';
import { contentKey } from '../features/content/useContent';
import { DICTATION_RESULT_KEY } from '../features/dictation/api';
import { REVIEW_KEY } from '../features/review/api';
import { LIBRARY_KEY, UPLOAD_USAGE_KEY } from '../features/library/useLibrary';
import { PENDING_KEYS, queryKeysForEvent } from './eventKeys';

const event = (type: LiveEventType, resourceId = 'r-1'): LiveEvent => ({
  id: '1',
  type,
  resourceId,
});

test('dictation.scored refreshes every Dictation result, whichever session it names', () => {
  expect(queryKeysForEvent(event('dictation.scored', 'attempt-1'), new QueryClient())).toEqual([
    DICTATION_RESULT_KEY,
    REVIEW_KEY,
  ]);
});

test('a pending Dictation result is refetched after a missed event', () => {
  expect(PENDING_KEYS).toContainEqual(DICTATION_RESULT_KEY);
});

test('the other events keep their keys', () => {
  const client = new QueryClient();
  expect(queryKeysForEvent(event('content.ready'), client)).toEqual([
    LIBRARY_KEY,
    contentKey('r-1'),
    UPLOAD_USAGE_KEY,
  ]);
  expect(queryKeysForEvent(event('job.progress'), client)).toEqual([
    LIBRARY_KEY,
    contentKey('r-1'),
  ]);
  expect(queryKeysForEvent(event('attempt.voided'), client)).toEqual([BLIND_KEY]);
  expect(queryKeysForEvent(event('export.ready'), client)).toEqual([EXPORTS_KEY]);
  expect(queryKeysForEvent(event('grade.ready'), client)).toEqual([]);
});

test('account.disabled refetches the learner, unless this tab is deleting the account', () => {
  const client = new QueryClient();
  expect(queryKeysForEvent(event('account.disabled'), client)).toEqual([ME_KEY]);

  const deleting = client
    .getMutationCache()
    .build(client, { mutationKey: DELETE_ACCOUNT_KEY, mutationFn: () => new Promise(() => {}) });
  void deleting.execute(undefined);
  expect(queryKeysForEvent(event('account.disabled'), client)).toEqual([]);
});
