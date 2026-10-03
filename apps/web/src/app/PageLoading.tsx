/** Shown while a page's code or the learner's account loads. No shimmer (design system). */
export function PageLoading() {
  return (
    <div
      role="status"
      className="mx-auto flex max-w-content items-center gap-2 px-4 py-8 text-ink-muted md:px-6 xl:px-8"
    >
      <span
        aria-hidden="true"
        className="size-3.5 animate-spin rounded-full border-2 border-current border-r-transparent"
      />
      Loading…
    </div>
  );
}
