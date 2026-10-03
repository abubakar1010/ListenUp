import { ErrorPanel } from '../components/ErrorPanel';

/** A whole page that is only an error, for when a page cannot show anything else. */
export function ErrorPage({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <main tabIndex={-1} className="mx-auto w-full max-w-content px-4 py-8 md:px-6 md:py-12 xl:px-8">
      <ErrorPanel error={error} onRetry={onRetry} headingLevel={1} />
    </main>
  );
}
