import { fireEvent, screen } from '@testing-library/react';

import { ApiError, type Problem } from '../api/client';
import { renderWithProviders } from '../test-utils';
import { ErrorPanel } from './ErrorPanel';

function apiError(status: number, code: string, detail: string): ApiError {
  const problem: Problem = { type: `/problems/${code}`, title: '', status, detail, code };
  return new ApiError(problem);
}

test('a missing item says what happened and links back to the library', () => {
  renderWithProviders(
    <ErrorPanel error={apiError(404, 'session_not_found', 'This session does not exist.')} />,
  );

  const alert = screen.getByRole('alert');
  expect(screen.getByRole('heading', { name: 'We could not find this' })).toBeInTheDocument();
  expect(alert).toHaveTextContent('This session does not exist.');
  expect(alert).toHaveTextContent('Check the link, or go back to your library.');
  expect(screen.getByRole('link', { name: 'Go to your library' })).toHaveAttribute(
    'href',
    '/library',
  );
});

test('an expired session offers to sign in and come back', () => {
  renderWithProviders(
    <ErrorPanel error={apiError(401, 'not_signed_in', 'Sign in to continue.')} />,
    { route: '/sessions/abc' },
  );

  expect(screen.getByRole('heading', { name: 'You are signed out' })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Sign in' })).toHaveAttribute(
    'href',
    '/sign-in?next=%2Fsessions%2Fabc',
  );
});

test('a lost connection offers a retry', () => {
  const onRetry = vi.fn();
  renderWithProviders(<ErrorPanel error={new TypeError('Failed to fetch')} onRetry={onRetry} />);

  expect(screen.getByRole('heading', { name: 'We could not reach ListenUp' })).toBeInTheDocument();
  expect(screen.getByRole('alert')).toHaveTextContent('Check your connection, then try again.');
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
  expect(onRetry).toHaveBeenCalledOnce();
});

test('a validation error names the fix and offers no button', () => {
  renderWithProviders(
    <ErrorPanel error={apiError(422, 'invalid_email', 'Enter a valid email address.')} />,
  );

  expect(screen.getByRole('alert')).toHaveTextContent('Enter a valid email address.');
  expect(screen.queryByRole('button')).not.toBeInTheDocument();
});

test('a page that failed to download asks for a reload', () => {
  renderWithProviders(
    <ErrorPanel error={new TypeError('Failed to fetch dynamically imported module: /x.js')} />,
  );

  expect(screen.getByRole('heading', { name: 'This page did not load' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Reload the page' })).toBeInTheDocument();
});
