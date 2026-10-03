import { useMemo, useReducer, useRef, useState, type FormEvent } from 'react';
import { Link, useNavigate, useParams } from 'react-router';

import { usePageTitle } from '../../app/usePageTitle';
import { buttonClass } from '../../components/button';
import { ErrorPanel } from '../../components/ErrorPanel';
import { BackIcon } from '../../components/icons';
import { useContent, type ContentDetail } from '../content/useContent';
import { useStartSession, type StartSession } from './api';
import { EntryChoice } from './EntryChoice';
import { PassagePicker } from './PassagePicker';
import { entryFrom } from './plan';
import { PlanPreview } from './PlanPreview';
import { defaultRange, firstSpeechMs, MIN_PASSAGE_MS } from './passage';
import { commitAll, initialPassage, passageReducer, selectedRange } from './passageState';
import { formatClock } from './time';
import { usePeaks } from './usePeaks';

const PAGE_CLASS =
  'mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 pt-4 pb-8 md:gap-8 md:px-6 md:pt-8 md:pb-12';

/**
 * Start a plan on a clip already in the library (`/contents/:contentId/plan`, FR-LB-2):
 * choose the passage, then Blind, Dictation or both (FR-PL-1), then start.
 */
export default function StartPlanPage() {
  const { contentId = '' } = useParams();
  usePageTitle('Start a plan');
  const clip = useContent(contentId);

  return (
    <main className={PAGE_CLASS}>
      <Link
        to="/library"
        className="inline-flex min-h-11 items-center gap-1 self-start font-bold text-accent no-underline"
      >
        <BackIcon />
        Library
      </Link>
      <div className="flex flex-col gap-1">
        <h1 className="font-display text-title-compact md:text-title">Start a plan</h1>
        {clip.data && <p className="text-body-l break-words">{clip.data.title}</p>}
      </div>
      {clip.isPending && (
        <p role="status" className="text-ink-muted">
          Loading the clip…
        </p>
      )}
      {clip.isError && <ErrorPanel error={clip.error} onRetry={() => void clip.refetch()} />}
      {clip.data && <ClipPlan clip={clip.data} />}
    </main>
  );
}

function ClipPlan({ clip }: { clip: ContentDetail }) {
  if (clip.status !== 'playable') {
    return (
      <p role="status" className="rounded-md border border-line bg-surface-raised p-4">
        {NOT_READY[clip.status]}
      </p>
    );
  }
  if (clip.duration_ms === null) {
    return (
      <p className="rounded-md border border-line bg-surface-raised p-4">
        The length of this clip is not known, so a part cannot be chosen yet. Try again later.
      </p>
    );
  }
  if (clip.duration_ms < MIN_PASSAGE_MS) {
    return (
      <p className="rounded-md border border-line bg-surface-raised p-4">
        This clip is {formatClock(clip.duration_ms)} long. A plan needs at least 30 seconds, so add
        a longer clip.
      </p>
    );
  }
  return <PlanForm clip={clip} durationMs={clip.duration_ms} />;
}

const NOT_READY: Record<Exclude<ContentDetail['status'], 'playable'>, string> = {
  pending: 'This clip is still being prepared. You can start a plan as soon as it is ready.',
  downloading: 'This clip is still downloading. You can start a plan as soon as it is ready.',
  failed: 'This clip could not be processed, so it cannot be practised. Add the file again.',
  expired: 'This clip needs downloading again before you can practise it.',
};

function PlanForm({ clip, durationMs }: { clip: ContentDetail; durationMs: number }) {
  const navigate = useNavigate();
  const start = useStartSession();
  const peaks = usePeaks(clip.peaks_url);
  const [passage, dispatch] = useReducer(passageReducer, durationMs, initialPassage);
  // The suggested part follows the first speech once the peaks arrive (ADR 0026).
  const base = useMemo(
    () => defaultRange(durationMs, peaks.data ? firstSpeechMs(peaks.data) : null),
    [durationMs, peaks.data],
  );
  const [blind, setBlind] = useState(true);
  const [dictation, setDictation] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  // One Idempotency-Key per distinct request: a retry of the same plan reuses it.
  const attempt = useRef<{ body: string; key: string } | null>(null);

  const entry = entryFrom(blind, dictation);

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    setSubmitted(true);
    // Typed times are applied first; one that is unreadable or was adjusted stops the
    // submit, so the learner sees why before the plan starts.
    const committed = commitAll(passage, base, durationMs);
    if (committed.state !== passage) dispatch({ type: 'replace', state: committed.state });
    if (committed.stop) {
      document.getElementById(`passage-${committed.stop}`)?.focus();
      return;
    }
    if (!entry) {
      document.getElementById('plan-blind')?.focus();
      return;
    }
    const range = selectedRange(committed.state, base, durationMs);
    const body: StartSession = {
      content_id: clip.id,
      passage: { start_ms: range.startMs, end_ms: range.endMs },
      entry,
    };
    const json = JSON.stringify(body);
    if (attempt.current?.body !== json) {
      attempt.current = { body: json, key: crypto.randomUUID() };
    }
    start.mutate(
      { body, key: attempt.current.key },
      { onSuccess: (session) => void navigate(`/sessions/${session.id}`) },
    );
  }

  return (
    <form noValidate onSubmit={onSubmit} className="flex flex-col gap-8">
      <section aria-labelledby="plan-passage" className="flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <h2 id="plan-passage" className="font-display text-heading-compact md:text-heading">
            1 · Choose the part to practise
          </h2>
          <p className="text-ink-muted">
            Any part from 30 seconds to 15 minutes. Two to three minutes works best.
          </p>
        </div>
        <PassagePicker
          durationMs={durationMs}
          state={passage}
          base={base}
          dispatch={dispatch}
          peaks={peaks.data ?? null}
          peaksFailed={peaks.isError}
          mediaUrl={clip.media_url}
        />
      </section>

      <section aria-labelledby="plan-entry" className="flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <h2 id="plan-entry" className="font-display text-heading-compact md:text-heading">
            2 · How do you want to start?
          </h2>
          <p className="text-ink-muted">
            Both let you hear the clip before you see any text. Pick one or both.
          </p>
        </div>
        <EntryChoice
          idPrefix="plan"
          blind={blind}
          dictation={dictation}
          onChange={(step, value) => (step === 'blind' ? setBlind(value) : setDictation(value))}
          error={submitted && !entry ? 'Tick Blind, Dictation or both.' : undefined}
        />
        <div className="flex flex-col gap-2 rounded-md bg-surface-sunken p-4">
          <p className="text-label text-ink-muted uppercase">Then, always</p>
          <p className="font-bold">Transcript → Card → Shadow</p>
          <p className="text-body-s">
            Transcript can't be skipped. Card and Shadow can be skipped, after you confirm.
          </p>
        </div>
        <div className="rounded-md border border-line bg-surface-raised p-4">
          <PlanPreview entry={entry} />
          {entry === 'both' && (
            <p className="mt-2 text-body-s text-ink-muted">
              With both, Blind comes first so your one listen is fresh.
            </p>
          )}
          <p className="mt-2 text-body-s text-ink-muted">
            You can change this until Transcript starts.
          </p>
        </div>
      </section>

      {start.isError && <ErrorPanel error={start.error} />}
      <button
        type="submit"
        className={buttonClass('primary', 'self-stretch sm:self-start')}
        disabled={start.isPending}
      >
        {start.isPending ? 'Starting…' : 'Start plan'}
      </button>
    </form>
  );
}
