import type { ComponentPropsWithRef, MouseEvent } from 'react';

interface BusyButtonProps extends Omit<ComponentPropsWithRef<'button'>, 'disabled'> {
  /** True while the request this button started is running. */
  busy: boolean;
}

/**
 * A button that stays focusable while its request runs (UX-10, WCAG 2.4.3). A natively
 * disabled button drops focus to the page body in Chromium, so the next Tab starts
 * again from the top; this one keeps focus, says it is busy (aria-busy, aria-disabled)
 * and ignores presses, including the implicit submit of its form, until it is done.
 * Pass the busy label as children, for example "Saving…".
 */
export function BusyButton({ busy, type = 'button', onClick, ...props }: BusyButtonProps) {
  return (
    <button
      {...props}
      type={type}
      aria-disabled={busy || props['aria-disabled'] || undefined}
      aria-busy={busy || undefined}
      onClick={(event: MouseEvent<HTMLButtonElement>) => {
        if (busy) {
          event.preventDefault();
          return;
        }
        onClick?.(event);
      }}
    />
  );
}
