import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';
import { Link } from 'react-router';

import { api, type Me } from '../api/client';
import { usePageTitle } from '../app/usePageTitle';
import { buttonClass } from '../components/button';
import { ErrorPanel } from '../components/ErrorPanel';
import { DOCUMENTS, useConsentVersions, useGrantConsents } from './consentApi';
import { errorMessage } from './errorMessage';
import { changeSession } from './session';
import { BusyButton } from '../components/BusyButton';

type Required = Me['consents_required'];

function names(kinds: Required): string {
  return kinds.map((kind) => DOCUMENTS[kind].name).join(' and ');
}

/**
 * A newer Terms of Service or Privacy Policy was published since the learner last
 * accepted one (#104). It is asked for once, before the app opens: accepting records
 * the current version; the learner may sign out instead.
 */
export default function ConsentPrompt({ required }: { required: Required }) {
  const title = `We updated our ${names(required)}`;
  usePageTitle(title);
  const heading = useRef<HTMLHeadingElement>(null);
  // The prompt can replace a page mid-visit (a refetched /me): move focus to it so
  // keyboard and screen-reader users learn why the page changed.
  useEffect(() => heading.current?.focus(), []);
  const versions = useConsentVersions();
  const grant = useGrantConsents();
  const queryClient = useQueryClient();
  const signOut = useMutation({
    meta: { changesSession: true },
    mutationFn: () => api<void>('/auth/logout', { method: 'POST' }),
    onSuccess: () => changeSession(queryClient, null),
  });

  function accept() {
    if (!versions.data) return;
    const current = versions.data;
    grant.mutate(required.map((kind) => ({ kind, version: current[kind] })));
  }

  return (
    <main id="main" className="mx-auto flex max-w-reading flex-col gap-5 p-6">
      <h1 ref={heading} tabIndex={-1} className="font-display text-title-compact">
        {title}
      </h1>
      <p>Read what changed, then accept to keep using ListenUp.</p>
      <ul className="list-disc pl-6">
        {required.map((kind) => (
          <li key={kind}>
            <Link to={DOCUMENTS[kind].path} target="_blank" className="font-bold text-accent">
              {DOCUMENTS[kind].name}
            </Link>
            {versions.data && ` (version ${versions.data[kind]})`}
          </li>
        ))}
      </ul>
      {versions.isError && (
        <ErrorPanel error={versions.error} onRetry={() => void versions.refetch()} />
      )}
      {(grant.isError || signOut.isError) && (
        <p role="alert" className="text-danger">
          {errorMessage(grant.error ?? signOut.error)}
        </p>
      )}
      <p>
        If you do not agree, you can{' '}
        <Link to="/settings" className="font-bold text-accent">
          download your data or delete your account
        </Link>
        , or sign out.
      </p>
      <div className="flex flex-wrap gap-3">
        <BusyButton
          className={buttonClass('primary')}
          onClick={accept}
          busy={!versions.data || grant.isPending}
        >
          {grant.isPending ? 'Saving…' : 'Accept and continue'}
        </BusyButton>
        <BusyButton
          className={buttonClass('secondary')}
          onClick={() => signOut.mutate()}
          busy={signOut.isPending}
        >
          {signOut.isPending ? 'Signing out…' : 'Sign out'}
        </BusyButton>
      </div>
    </main>
  );
}
