import { useEffect, useRef, useState, type ReactNode, type FormEvent } from 'react';
import { Link } from 'react-router';
import { buttonClass } from '../../components/button';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { ErrorPanel } from '../../components/ErrorPanel';
import { useMarks, useTranscript } from '../review/api';
import { useSkipStep, type Session } from '../session/api';
import { PracticeLayout } from '../session/PracticeLayout';
import { STEP_RULES } from '../session/plan';
import { formatClock } from '../session/time';
import { CardAudio } from './CardAudio';
import {
  useCardSuggestions,
  useCards,
  useCreateCard,
  useDeleteCard,
  useFinishCards,
  type Card,
  type CardSuggestion,
  type NewCard,
} from './api';

const REASON_TEXT: Record<CardSuggestion['reasons'][number], string> = {
  multi_word: 'several words',
  linking: 'tagged linking',
  reduction: 'tagged reduction',
  weak_form: 'tagged weak form',
  earlier_session: 'marked in an earlier session',
};

const inputClass =
  'min-h-11 w-full min-w-0 rounded-md border border-line-strong bg-surface-raised px-3 py-2';

export function CardScreen({ session, progress }: { session: Session; progress: ReactNode }) {
  const cards = useCards(session.id);
  const marks = useMarks(session.id);
  const transcript = useTranscript(session.id);
  const suggestions = useCardSuggestions(session.id);
  const [selected, setSelected] = useState('');
  const [written, setWritten] = useState('');
  const [heard, setHeard] = useState('');
  const [deleting, setDeleting] = useState<Card | null>(null);
  const [skipping, setSkipping] = useState(false);
  const [announcement, setAnnouncement] = useState('');
  const heading = useRef<HTMLHeadingElement>(null);
  const retry = useRef<{ fingerprint: string; key: string } | null>(null);
  const create = useCreateCard(session.id, () => {
    setHeard('');
    retry.current = null;
  });
  const remove = useDeleteCard(session.id, () => setDeleting(null));
  const finish = useFinishCards(session.id);
  const skip = useSkipStep(session);
  const remaining = cards.data?.remaining ?? 0;
  const busy = create.isPending || remove.isPending || finish.isPending || skip.isPending;
  const blocked = !cards.data || cards.isError || remaining === 0 || busy;
  useEffect(() => {
    heading.current?.focus();
  }, []);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (cards.data) setAnnouncement(`${remaining} left`);
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [remaining, cards.data]);
  const words = transcript.data?.lines.flatMap((line) => line.words) ?? [];
  const markList = marks.data?.marks ?? [];
  const bySuggestion = new Map(suggestions.data?.suggestions.map((item) => [item.mark_id, item]));
  // Suggestions only reorder; a mark they do not know about is listed after them.
  const ordered = suggestions.data
    ? [
        ...suggestions.data.suggestions.flatMap((item) =>
          markList.filter((mark) => mark.id === item.mark_id),
        ),
        ...markList.filter((mark) => !bySuggestion.has(mark.id)),
      ]
    : markList;
  const suggestedMarks = ordered.filter((mark) => bySuggestion.get(mark.id)?.suggested);
  const otherMarks = ordered.filter((mark) => !bySuggestion.get(mark.id)?.suggested);
  const chosenReasons = bySuggestion.get(selected)?.suggested
    ? bySuggestion.get(selected)!.reasons.map((reason) => REASON_TEXT[reason])
    : [];
  function phraseOf(mark: { word_from: number; word_to: number }) {
    return words
      .filter((word) => word.index >= mark.word_from && word.index <= mark.word_to)
      .map((word) => word.text)
      .join(' ');
  }
  function option(mark: (typeof markList)[number]) {
    return (
      <option key={mark.id} value={mark.id}>
        {phraseOf(mark) || 'Marked phrase'} · {formatClock(mark.at_ms)}
      </option>
    );
  }
  function choose(id: string) {
    setSelected(id);
    const mark = markList.find((mark) => mark.id === id);
    setWritten(mark ? phraseOf(mark).slice(0, 100) : '');
  }
  function save(event: FormEvent) {
    event.preventDefault();
    if (blocked || !selected) return;
    const body: NewCard = { mark_id: selected, written_form: written, heard_form: heard };
    const fingerprint = JSON.stringify(body);
    if (retry.current?.fingerprint !== fingerprint)
      retry.current = { fingerprint, key: crypto.randomUUID() };
    create.mutate({ body, key: retry.current.key });
  }
  return (
    <PracticeLayout
      heading={`Card: ${session.content_title}`}
      clipTitle={session.content_title}
      clipMeta={`Passage ${formatClock(session.passage.start_ms)} to ${formatClock(session.passage.end_ms)}`}
      back={{ to: '/library', label: 'Library' }}
      progress={progress}
      player={null}
      rule={STEP_RULES.card}
      workLabel="Card"
    >
      <h2 ref={heading} tabIndex={-1} className="font-display text-heading">
        Keep a sound you missed
      </h2>
      <p>
        Choose a marked phrase, then write how it sounded. Phonetic symbols or plain respelling both
        work.
      </p>
      <p className="font-bold">{cards.data ? `${remaining} left` : 'Loading cards…'}</p>
      <p role="status" className="sr-only">
        {announcement}
      </p>
      {cards.isError && <ErrorPanel error={cards.error} onRetry={() => void cards.refetch()} />}
      {marks.isError && <ErrorPanel error={marks.error} onRetry={() => void marks.refetch()} />}
      {transcript.isError && (
        <p>
          The marked words are unavailable. You can still choose a time and enter the written form.
        </p>
      )}
      {marks.data?.marks.length === 0 && (
        <p>No marks in this session. You can finish Card or skip it.</p>
      )}
      <form onSubmit={save} className="flex min-w-0 flex-col gap-3" aria-busy={create.isPending}>
        <label className="flex flex-col gap-1">
          Marked phrase
          <select
            className={inputClass}
            value={selected}
            aria-describedby={chosenReasons.length > 0 ? 'card-suggestion-reason' : undefined}
            onChange={(event) => choose(event.target.value)}
            required
          >
            <option value="">Choose a mark</option>
            {suggestedMarks.length > 0 ? (
              <>
                <optgroup label="Suggested phrases">{suggestedMarks.map(option)}</optgroup>
                <optgroup label="Other marks">{otherMarks.map(option)}</optgroup>
              </>
            ) : (
              ordered.map(option)
            )}
          </select>
        </label>
        {suggestedMarks.length > 0 && (
          <p>Suggestions are only a nudge. Choose any mark, or none, and Save card to keep it.</p>
        )}
        {chosenReasons.length > 0 && (
          <p id="card-suggestion-reason">Suggested: {chosenReasons.join(', ')}.</p>
        )}
        <label className="flex flex-col gap-1">
          Written form
          <input
            className={inputClass}
            required
            minLength={1}
            maxLength={100}
            value={written}
            onChange={(event) => setWritten(event.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1">
          Heard form
          <input
            className={inputClass}
            required
            minLength={1}
            maxLength={100}
            value={heard}
            onChange={(event) => setHeard(event.target.value)}
          />
        </label>
        <button
          className={buttonClass('primary', 'self-start')}
          type="submit"
          aria-disabled={blocked}
          aria-describedby={blocked ? 'card-save-reason' : undefined}
        >
          {create.isPending ? 'Saving…' : 'Save card'}
        </button>
        {blocked && (
          <p id="card-save-reason">
            {remaining === 0 && cards.data
              ? 'Two cards saved. Delete a card to free a slot.'
              : cards.isError
                ? 'Reload your cards before saving another card.'
                : 'Wait until your cards are ready.'}
          </p>
        )}
      </form>
      {create.isError && <ErrorPanel error={create.error} />}
      <ul aria-label="Saved cards" className="flex flex-col gap-3">
        {cards.data?.cards.map((card) => (
          <li
            key={card.id}
            className="flex min-w-0 flex-col gap-2 rounded-md border border-line p-3 break-words"
          >
            <p>
              <strong>{card.written_form}</strong> → {card.heard_form}
            </p>
            <CardAudio card={card} />
            <Link to={card.source_url} className="min-h-11 py-2 font-bold text-accent">
              Source at {formatClock(card.at_ms)}
            </Link>
            <button
              type="button"
              className={buttonClass('quiet', 'self-start')}
              aria-disabled={busy}
              onClick={() => {
                if (!busy) {
                  remove.reset();
                  setDeleting(card);
                }
              }}
            >
              Delete card: {card.written_form}
            </button>
          </li>
        ))}
      </ul>
      <button
        type="button"
        className={buttonClass('primary', 'self-start')}
        aria-disabled={busy || !cards.data}
        onClick={() => {
          if (!busy && cards.data) finish.mutate();
        }}
      >
        Finish Card
      </button>
      {finish.isError && <ErrorPanel error={finish.error} />}
      <button
        type="button"
        className={buttonClass('quiet', 'self-start')}
        aria-disabled={busy}
        onClick={() => {
          if (!busy) setSkipping(true);
        }}
      >
        Skip Card
      </button>
      {deleting && (
        <ConfirmDialog
          title="Delete this card?"
          confirmLabel="Delete card"
          cancelLabel="Keep card"
          busy={remove.isPending}
          onCancel={() => setDeleting(null)}
          onConfirm={() => remove.mutate(deleting.id)}
          footer={remove.isError ? <ErrorPanel error={remove.error} /> : undefined}
        >
          Deleting this card frees one slot in this session.
        </ConfirmDialog>
      )}
      {skipping && (
        <ConfirmDialog
          title="Skip Card?"
          confirmLabel="Skip Card"
          cancelLabel="Make a card"
          busy={skip.isPending}
          onCancel={() => setSkipping(false)}
          onConfirm={() => skip.mutate('card')}
          footer={skip.isError ? <ErrorPanel error={skip.error} /> : undefined}
        >
          If you skip, you can't make cards for this session.
        </ConfirmDialog>
      )}
    </PracticeLayout>
  );
}
