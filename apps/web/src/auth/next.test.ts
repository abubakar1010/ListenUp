import { nextPath, signInPath } from './next';

test.each([
  ['?next=%2Fsessions%2Fabc', '/sessions/abc'],
  ['?next=/library?tab=marks', '/library?tab=marks'],
  ['', '/library'],
  ['?next=https://evil.example', '/library'],
  ['?next=//evil.example', '/library'],
  ['?next=/\\evil.example', '/library'],
  ['?next=javascript:alert(1)', '/library'],
])('nextPath(%s) is %s', (search, expected) => {
  expect(nextPath(search)).toBe(expected);
});

test('signInPath keeps the whole address to come back to', () => {
  expect(signInPath({ pathname: '/sessions/abc', search: '?step=2', hash: '#work' })).toBe(
    '/sign-in?next=%2Fsessions%2Fabc%3Fstep%3D2%23work',
  );
  expect(signInPath({ pathname: '/', search: '', hash: '' })).toBe('/sign-in');
});
