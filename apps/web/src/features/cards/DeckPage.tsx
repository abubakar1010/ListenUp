import { useCallback, useRef, useState } from 'react';
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router';
import { api } from '../../api/client';
import type { components } from '../../api/schema';
import { ErrorPanel } from '../../components/ErrorPanel';
import { PageTitle } from '../../app/PageTitle';
import { buttonClass } from '../../components/button';
import type { Card } from './api';

type History = components['schemas']['ReviewHistory'];
type Result = components['schemas']['ReviewResult']['result'];

export default function DeckPage() {
  const deck = useInfiniteQuery({
    queryKey: ['cards', 'deck'],
    initialPageParam: '',
    queryFn: ({ pageParam }) =>
      api<components['schemas']['CardList']>(
        `/cards${pageParam ? `?cursor=${encodeURIComponent(pageParam)}` : ''}`,
      ),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    refetchInterval: (query) =>
      query.state.data?.pages.some((page) =>
        page.cards.some((card) => card.audio_status === 'pending'),
      )
        ? 1000
        : false,
  });
  const [index, setIndex] = useState(0);
  const cards = deck.data?.pages.flatMap((page) => page.cards) ?? [];
  const card = cards[index];
  return (
    <main id="main" tabIndex={-1} className="mx-auto w-full max-w-3xl space-y-6 p-4 md:p-8">
      <PageTitle title="Review cards" />
      <h1 className="text-title">Review cards</h1>
      <p>Listen first, then reveal the forms and record what you heard.</p>
      {deck.isPending && <p role="status">Loading cards…</p>}
      {deck.isError && <ErrorPanel error={deck.error} />}
      {deck.isSuccess && !cards.length && (
        <p>No saved cards yet. Create cards from marks during practice.</p>
      )}
      {card && <ReviewCard key={card.id} card={card} />}
      {cards.length > 0 && (
        <nav aria-label="Card deck" className="flex flex-wrap items-center gap-3">
          <button
            className={buttonClass('quiet')}
            disabled={index === 0}
            onClick={() => setIndex(index - 1)}
          >
            Previous card
          </button>
          <p role="status">
            Card {Math.min(index + 1, cards.length)} of {cards.length}
            {deck.hasNextPage ? '+' : ''}
          </p>
          <button
            className={buttonClass('quiet')}
            aria-disabled={index + 1 >= cards.length}
            onClick={() => {
              if (index + 1 < cards.length) setIndex(index + 1);
            }}
          >
            Next card
          </button>
          {index + 1 >= cards.length &&
            (deck.hasNextPage ? (
              <button
                className={buttonClass('quiet')}
                disabled={deck.isFetchingNextPage}
                onClick={() => void deck.fetchNextPage()}
              >
                Load more cards
              </button>
            ) : (
              <p>End of deck</p>
            ))}
        </nav>
      )}
    </main>
  );
}

function ReviewCard({ card }: { card: Card }) {
  const [listened, setListened] = useState(false);
  const [revealed, setRevealed] = useState(false);
  const client = useQueryClient();
  const history = useQuery({
    queryKey: ['cards', 'reviews', card.id],
    queryFn: () => api<History>(`/cards/${card.id}/reviews`),
  });
  const key = useRef<string | null>(null);
  const lastResult = useRef<Result | null>(null);
  const save = useMutation({
    mutationFn: (result: Result) => {
      if (!key.current || lastResult.current !== result) key.current = crypto.randomUUID();
      lastResult.current = result;
      return api<components['schemas']['CardReview']>(`/cards/${card.id}/reviews`, {
        method: 'POST',
        body: { result },
        headers: { 'Idempotency-Key': key.current },
      });
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['cards', 'reviews', card.id] });
    },
  });
  return (
    <section
      aria-label="Current card"
      className="space-y-4 rounded-lg border border-line bg-surface-raised p-4 break-words"
    >
      <Snippet card={card} onListened={() => setListened(true)} />
      <button
        className={buttonClass('quiet')}
        disabled={!listened}
        onClick={() => setRevealed(true)}
      >
        Reveal forms
      </button>
      {!listened && <p>Play the full snippet to unlock reveal.</p>}
      {revealed && (
        <>
          <dl className="space-y-2">
            <dt className="font-bold">Written form</dt>
            <dd>{card.written_form}</dd>
            <dt className="font-bold">Heard form</dt>
            <dd>{card.heard_form}</dd>
          </dl>
          <Link to={card.source_url}>Open source</Link>
          <fieldset aria-busy={save.isPending} className="space-y-2">
            <legend>How did you hear it?</legend>
            <div className="flex flex-wrap gap-3">
              {(['heard', 'unsure', 'missed'] as const).map((result) => (
                <button
                  key={result}
                  className={buttonClass('quiet')}
                  aria-disabled={save.isPending || save.isSuccess}
                  onClick={() => {
                    if (!save.isPending && !save.isSuccess) save.mutate(result);
                  }}
                >
                  {result[0].toUpperCase() + result.slice(1)}
                </button>
              ))}
            </div>
          </fieldset>
          {save.isPending && <p role="status">Saving result…</p>}
          {save.isSuccess && <p role="status">Saved: {save.data.result}</p>}
          {save.isError && <ErrorPanel error={save.error} />}
          {history.isError && <ErrorPanel error={history.error} />}
          {history.data && history.data.reviews.length > 0 && (
            <div>
              <h2 className="font-bold">Recent results</h2>
              <ul>
                {history.data.reviews.map((review) => (
                  <li key={review.id}>
                    {review.result} —{' '}
                    <time dateTime={review.reviewed_at}>
                      {new Date(review.reviewed_at).toLocaleString()}
                    </time>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </section>
  );
}

function Snippet({ card, onListened }: { card: Card; onListened: () => void }) {
  const audio = useRef<HTMLAudioElement | null>(null);
  const [error, setError] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(false);
  const retry = useMutation({
    mutationFn: () => api<void>(`/cards/${card.id}/audio/retry`, { method: 'POST' }),
  });
  const client = useQueryClient();
  // Ref cleanup pauses even when this card is replaced or its page is left.
  const attach = useCallback((element: HTMLAudioElement | null) => {
    if (!element) audio.current?.pause();
    audio.current = element;
  }, []);
  async function play() {
    if (!audio.current || loading) return;
    if (playing) {
      audio.current.pause();
      return;
    }
    setError(false);
    setLoading(true);
    audio.current.src = `/api/v1/cards/${encodeURIComponent(card.id)}/audio`;
    try {
      await audio.current.play();
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }
  return (
    <div className="space-y-2">
      <audio
        ref={attach}
        preload="none"
        onPlaying={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => {
          setPlaying(false);
          onListened();
        }}
        onError={() => {
          setError(true);
          setPlaying(false);
          setLoading(false);
        }}
      />
      <button
        className={buttonClass('quiet')}
        disabled={card.audio_status !== 'ready' || loading}
        onClick={() => void play()}
      >
        {playing ? 'Pause snippet' : 'Play snippet'}
      </button>
      {card.audio_status === 'pending' && <p role="status">Preparing audio…</p>}
      {card.audio_status === 'unavailable' && (
        <p>Audio is unavailable for this older card. You can move to another card.</p>
      )}
      {card.audio_status === 'failed' && (
        <>
          <p>Audio preparation failed.</p>
          <button
            className={buttonClass('quiet')}
            disabled={retry.isPending}
            onClick={() =>
              retry.mutate(undefined, {
                onSuccess: () => {
                  void client.invalidateQueries({ queryKey: ['cards', 'deck'] });
                },
              })
            }
          >
            Retry audio
          </button>
        </>
      )}
      {retry.isError && <ErrorPanel error={retry.error} />}
      {error && <p role="alert">The snippet could not play. Try playing it again.</p>}
    </div>
  );
}
