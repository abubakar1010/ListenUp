import { ApiError } from '../api/client';

/** What the learner can do about an error; ErrorPanel turns it into a button or a link. */
export type ErrorAction = 'retry' | 'reload' | 'sign-in' | 'library' | null;

export interface ErrorView {
  /** What happened, in a few words. */
  title: string;
  /** The specifics: the server's `detail` for API errors. */
  detail: string;
  /** What to do next, as one sentence (NFR-USE-3). */
  nextStep: string;
  action: ErrorAction;
}

function isChunkLoadError(error: unknown): boolean {
  // Chrome, Firefox and Safari word a failed lazy import differently.
  return (
    error instanceof Error &&
    /dynamically imported module|Importing a module script failed|error loading dynamically/i.test(
      error.message,
    )
  );
}

function isNetworkError(error: unknown): boolean {
  return error instanceof TypeError;
}

/**
 * Turns any error into words for the learner: what happened and what to do next
 * (NFR-USE-3). API errors use the problem's `detail` and pick the next step from
 * its status; the problem's own `title` is the HTTP phrase ("Not Found"), so it
 * is used only when no friendlier title fits.
 */
export function describeError(error: unknown): ErrorView {
  if (error instanceof ApiError) {
    const { status, detail, title } = error.problem;
    if (status === 401 || error.code === 'not_signed_in') {
      return {
        title: 'You are signed out',
        detail,
        nextStep: 'Sign in again to carry on where you stopped.',
        action: 'sign-in',
      };
    }
    if (status === 403 || status === 404) {
      return {
        title: 'We could not find this',
        detail,
        nextStep: 'Check the link, or go back to your library.',
        action: 'library',
      };
    }
    if (status === 409) {
      return {
        title: 'This cannot be done right now',
        detail,
        nextStep: 'Reload the page to see the latest state, then try again.',
        action: 'reload',
      };
    }
    if (status === 400 || status === 422) {
      return {
        title: 'Something needs fixing',
        detail,
        nextStep: 'Change what the message says, then try again.',
        action: null,
      };
    }
    if (status === 429) {
      return {
        title: 'Too many tries',
        detail,
        nextStep: 'Wait a minute, then try again.',
        action: 'retry',
      };
    }
    if (status >= 500) {
      return {
        title: 'Something went wrong on our side',
        detail,
        nextStep: 'Try again in a moment.',
        action: 'retry',
      };
    }
    return {
      title: title || 'Something went wrong',
      detail,
      nextStep: 'Try again.',
      action: 'retry',
    };
  }

  if (isChunkLoadError(error)) {
    return {
      title: 'This page did not load',
      detail: 'A new version of ListenUp may be out, or the connection dropped.',
      nextStep: 'Reload the page.',
      action: 'reload',
    };
  }
  if (isNetworkError(error)) {
    return {
      title: 'We could not reach ListenUp',
      detail: 'The connection may have dropped.',
      nextStep: 'Check your connection, then try again.',
      action: 'retry',
    };
  }
  return {
    title: 'This page stopped working',
    detail: 'Something unexpected happened on this page.',
    nextStep: 'Reload the page. If it happens again, go back to your library.',
    action: 'reload',
  };
}
