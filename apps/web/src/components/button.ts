/*
 * Button styles from the design system's Button component (lu-btn): 44 px tall,
 * radius-m, bold body text. Use on <button> and on <Link> alike.
 */
const BASE =
  'inline-flex min-h-11 items-center justify-center gap-2 rounded-md border px-4 py-2 font-sans text-body font-bold no-underline transition-colors duration-120 ease-enter cursor-pointer aria-disabled:cursor-not-allowed aria-disabled:border-line aria-disabled:bg-surface-sunken aria-disabled:text-ink-muted disabled:cursor-not-allowed disabled:border-line disabled:bg-surface-sunken disabled:text-ink-muted';

const VARIANTS = {
  primary: 'border-transparent bg-accent text-on-accent hover:bg-accent-hover hover:text-on-accent',
  secondary: 'border-line-strong bg-surface-raised text-ink hover:border-ink hover:text-ink',
  quiet: 'border-transparent bg-transparent px-3 text-accent hover:bg-accent-soft',
} as const;

export type ButtonVariant = keyof typeof VARIANTS;

export function buttonClass(variant: ButtonVariant = 'secondary', extra = ''): string {
  return `${BASE} ${VARIANTS[variant]} ${extra}`.trim();
}
