import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useEffect, useId, useRef, useState } from 'react';

import { api, type Me } from '../api/client';
import { ME_KEY } from '../auth/useMe';
import { buttonClass } from '../components/button';
import { describeError } from '../components/describeError';

function initials(me: Me): string {
  const source = me.display_name?.trim() || me.email;
  const parts = source.split(/[\s@._-]+/).filter(Boolean);
  return (parts.length > 1 ? parts[0][0] + parts[1][0] : source.slice(0, 2)).toUpperCase();
}

/**
 * The account button in the header. It opens a small panel with who is signed in
 * and "Sign out". Escape or a click outside closes it.
 */
export function AccountMenu({ me }: { me: Me }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const queryClient = useQueryClient();

  const signOut = useMutation({
    mutationFn: () => api<void>('/auth/logout', { method: 'POST' }),
    onSuccess: () => {
      // Drop everything cached for this learner; the signed-in guard then sends
      // the page to sign in.
      queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== ME_KEY[0] });
      queryClient.setQueryData(ME_KEY, null);
    },
  });

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: PointerEvent) {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setOpen(false);
        button.current?.focus();
      }
    }
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  return (
    <div ref={root} className="relative">
      <button
        ref={button}
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((value) => !value)}
        className="inline-grid size-11 cursor-pointer place-items-center rounded-full"
      >
        <span className="sr-only">Account</span>
        <span
          aria-hidden="true"
          className="inline-grid size-9 place-items-center rounded-full border border-line-strong bg-accent-soft text-body-s font-bold text-ink"
        >
          {initials(me)}
        </span>
      </button>
      <div
        id={panelId}
        hidden={!open}
        className="absolute top-full right-0 z-20 mt-2 flex w-72 max-w-[calc(100vw-2rem)] flex-col gap-3 rounded-md border border-line-strong bg-surface-raised p-4 shadow-dialog"
      >
        <p className="text-body-s break-words">
          Signed in as <span className="font-bold">{me.email}</span>
        </p>
        <button
          type="button"
          onClick={() => signOut.mutate()}
          disabled={signOut.isPending}
          className={buttonClass('secondary')}
        >
          {signOut.isPending ? 'Signing out…' : 'Sign out'}
        </button>
        {signOut.isError && (
          <p role="alert" className="text-body-s text-danger">
            {describeError(signOut.error).title}. {describeError(signOut.error).nextStep}
          </p>
        )}
      </div>
    </div>
  );
}
