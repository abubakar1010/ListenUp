import { useEffect, useId, useRef, type KeyboardEvent, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

import { buttonClass } from './button';

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * A modal sheet for reading, not deciding (WAI-ARIA dialog pattern): a bottom sheet
 * below 768 px and a centred panel above it (UX-18). Focus starts on Close and stays
 * inside; Escape, Close and the scrim close it, and focus returns to the control that
 * opened it. Render it only while it is open; use ConfirmDialog for a choice.
 */
export function Sheet({
  title,
  children,
  onClose,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
}) {
  const titleId = useId();
  const sheet = useRef<HTMLDivElement>(null);
  const close = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    close.current?.focus();
    return () => {
      window.setTimeout(() => {
        if (opener && opener !== document.body && opener.isConnected) opener.focus();
      });
    };
  }, []);

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape') {
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== 'Tab' || !sheet.current) return;
    const focusable = [...sheet.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement;
    if (event.shiftKey && (active === first || !sheet.current.contains(active))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && (active === last || !sheet.current.contains(active))) {
      event.preventDefault();
      first.focus();
    }
  }

  return createPortal(
    <div
      data-testid="sheet-scrim"
      className="fixed inset-0 z-50 grid items-end bg-scrim p-0 md:place-items-center md:p-6"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={sheet}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onKeyDown={onKeyDown}
        className="flex max-h-[85vh] w-full flex-col gap-4 overflow-y-auto rounded-t-lg bg-surface-raised p-6 pb-[max(1.5rem,env(safe-area-inset-bottom))] shadow-dialog md:max-w-md md:rounded-lg"
      >
        <div className="flex items-center justify-between gap-4">
          <h2 id={titleId} className="font-display text-heading">
            {title}
          </h2>
          <button ref={close} type="button" className={buttonClass('quiet')} onClick={onClose}>
            Close
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}
