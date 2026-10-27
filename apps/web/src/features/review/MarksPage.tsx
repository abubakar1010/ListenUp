import { useInfiniteQuery } from '@tanstack/react-query';
import { Link } from 'react-router';
import { api } from '../../api/client';
import type { components } from '../../api/schema';
import { PageTitle } from '../../app/PageTitle';
import { ErrorPanel } from '../../components/ErrorPanel';
import { buttonClass } from '../../components/button';

export default function MarksPage() {
  const marks = useInfiniteQuery({
    queryKey: ['saved-marks'],
    initialPageParam: '',
    queryFn: ({ pageParam }) =>
      api<components['schemas']['SavedMarkList']>(
        `/marks${pageParam ? `?cursor=${encodeURIComponent(pageParam)}` : ''}`,
      ),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
  const rows = marks.data?.pages.flatMap((page) => page.marks) ?? [];
  return (
    <main id="main" tabIndex={-1} className="mx-auto w-full max-w-3xl space-y-6 p-4 md:p-8">
      <PageTitle title="Saved marks" />
      <h1 className="text-title">Saved marks</h1>
      <p>Marks from all your sessions, newest first.</p>
      {marks.isPending && <p role="status">Loading marks…</p>}
      {marks.isError && <ErrorPanel error={marks.error} />}
      {marks.isSuccess && !rows.length && <p>No saved marks yet.</p>}
      <ul className="space-y-4">
        {rows.map((mark) => (
          <li key={mark.id} className="space-y-2 rounded-lg border border-line p-4 break-words">
            <Link to={mark.source_url}>
              Open source at {(mark.at_ms / 1000).toFixed(1)} seconds
            </Link>
            <p>
              {mark.source === 'dictation' ? 'Dictation' : 'Manual'} mark · {mark.status}
            </p>
            {mark.note && <p className="whitespace-pre-wrap">{mark.note}</p>}
            <p>
              <time dateTime={mark.created_at}>{new Date(mark.created_at).toLocaleString()}</time>
            </p>
            <Link to={`/sessions/${mark.session_id}`}>Open practice session</Link>
          </li>
        ))}
      </ul>
      {marks.hasNextPage && (
        <button
          className={buttonClass('quiet')}
          disabled={marks.isFetchingNextPage}
          onClick={() => void marks.fetchNextPage()}
        >
          Load more marks
        </button>
      )}
    </main>
  );
}
