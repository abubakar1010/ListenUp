import { browserCheck, expect, test } from './test';

test('an unavailable assertion is explicitly reported without running it', async () => {
  let ran = false;
  await browserCheck('recording container bytes', 'driver does not expose Blob bodies', () => {
    ran = true;
  });
  expect(ran).toBe(false);
  expect(test.info().annotations).toContainEqual({
    type: 'skipped-check',
    description: 'recording container bytes: driver does not expose Blob bodies',
  });
});

test('an available assertion still rejects the defect', async () => {
  await expect(
    browserCheck('recording container bytes', undefined, () => {
      throw new Error('wrong container');
    }),
  ).rejects.toThrow('wrong container');
});
