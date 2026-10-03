import { focusMain } from './focusMain';

/** The first stop for Tab on every page: jumps past the header to the content. */
export function SkipLink() {
  return (
    <a
      href="#main"
      onClick={(event) => {
        event.preventDefault();
        focusMain();
      }}
      className="sr-only rounded-md bg-surface-raised px-4 py-3 font-bold text-accent shadow-raised focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50"
    >
      Skip to content
    </a>
  );
}
