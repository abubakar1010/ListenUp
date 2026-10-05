import { stageLabel, stageSentence } from './intakeStatus';

test.each([
  [{ stage: 'queued', queue_position: 1 }, 'Queued · 1st in line'],
  [{ stage: 'queued', queue_position: 2 }, 'Queued · 2nd in line'],
  [{ stage: 'queued', queue_position: 3 }, 'Queued · 3rd in line'],
  [{ stage: 'queued', queue_position: 11 }, 'Queued · 11th in line'],
  [{ stage: 'queued', queue_position: 22 }, 'Queued · 22nd in line'],
  [{ stage: 'waiting' }, 'Waiting to start'],
  [{ stage: 'checking' }, 'Checking the file'],
  [{ stage: 'converting' }, 'Converting'],
  [{ stage: 'saving' }, 'Almost ready'],
  [{}, 'Processing'],
] as const)('a clip being prepared at %o shows "%s"', (fields, label) => {
  expect(stageLabel({ status: 'pending', ...fields })).toBe(label);
});

test('a prepared or failed clip has no stage label', () => {
  expect(stageLabel({ status: 'playable', stage: null })).toBeNull();
  expect(stageLabel({ status: 'failed', stage: null })).toBeNull();
});

test('the clip page explains the queue and that it updates by itself', () => {
  expect(stageSentence({ status: 'pending', stage: 'queued', queue_position: 2 })).toBe(
    'Waiting for your other clips: two of your clips are prepared at a time. It is 2nd in line. This page updates by itself when the clip is ready.',
  );
  expect(stageSentence({ status: 'pending', stage: 'converting' })).toBe(
    'Converting it for playback. This page updates by itself when the clip is ready.',
  );
});
