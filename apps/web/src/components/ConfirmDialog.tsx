import { useEffect, useId, useRef, type KeyboardEvent, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

import { buttonClass } from './button';

interface ConfirmDialogProps {
  title: string;
  /** What is lost by confirming. */
  children: ReactNode;
  /** The action that is confirmed, for example "Skip Card". */
  confirmLabel: string;
  /** The safe action, which keeps things as they are, for example "Make a card". */
  cancelLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
  busy?: boolean;
  /** Shown inside the dialog, for example an ErrorPanel after a refused request. */
  footer?: ReactNode;
}

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * A modal confirmation (WAI-ARIA dialog pattern). Focus starts on the safe action and
 * stays inside the dialog; Escape and the scrim cancel. When it closes, focus returns
 * to the control that opened it, or to the page's <main> if that control is gone.
 * Render it only while it is open.
 */
export function ConfirmDialog({
  title,
  children,
  confirmLabel,
  cancelLabel,
  onConfirm,
  onCancel,
  busy = false,
  footer,
}: ConfirmDialogProps) {
  const titleId = useId();
  const bodyId = useId();
  const dialog = useRef<HTMLDivElement>(null);
  const safe = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    safe.current?.focus();
    return () => {
      // After the update that closed the dialog: the opener may be gone by then (a
      // skipped step's own button), and focus then goes to the page's <main>.
      window.setTimeout(() => {
        if (opener && opener !== document.body && opener.isConnected) {
          opener.focus();
          return;
        }
        const main = document.querySelector<HTMLElement>('main');
        if (main) {
          if (!main.hasAttribute('tabindex')) main.setAttribute('tabindex', '-1');
          main.focus();
        }
      });
    };
  }, []);

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape') {
      event.stopPropagation();
      if (!busy) onCancel();
      return;
    }
    if (event.key !== 'Tab' || !dialog.current) return;
    const focusable = [...dialog.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement;
    if (event.shiftKey && (active === first || !dialog.current.contains(active))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && (active === last || !dialog.current.contains(active))) {
      event.preventDefault();
      first.focus();
    }
  }

  return createPortal(
    <div
      className="fixed inset-0 z-50 grid items-end bg-scrim p-0 sm:place-items-center sm:p-6"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) onCancel();
      }}
    >
      <div
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={bodyId}
        onKeyDown={onKeyDown}
        className="flex w-full flex-col gap-4 rounded-t-lg bg-surface-raised p-6 shadow-dialog sm:max-w-md sm:rounded-lg"
      >
        <h2 id={titleId} className="font-display text-heading">
          {title}
        </h2>
        <div id={bodyId}>{children}</div>
        {footer}
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button
            type="button"
            className={buttonClass('secondary')}
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? 'Saving…' : confirmLabel}
          </button>
          <button
            ref={safe}
            type="button"
            className={buttonClass('primary')}
            onClick={onCancel}
            disabled={busy}
          >
            {cancelLabel}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
