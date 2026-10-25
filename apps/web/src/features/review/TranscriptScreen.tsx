import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent,
  type ReactNode,
} from 'react';
import { TranscriptGistPanel } from '../blind/GistFeedback';
import { ApiError } from '../../api/client';
import { buttonClass } from '../../components/button';
import { ErrorPanel } from '../../components/ErrorPanel';
import type { OpenMarkList } from '../dictation/api';
import { DictationResultPanel } from '../dictation/DictationResultPanel';
import { PassagePlayerControls } from '../media/PassagePlayerControls';
import { actionFor, stepSpeed } from '../media/playerPolicy';
import { usePassagePlayer, type PassagePlayer } from '../media/usePassagePlayer';
import type { Session } from '../session/api';
import { PracticeLayout } from '../session/PracticeLayout';
import { STEP_RULES } from '../session/plan';
import { formatClock } from '../session/time';
import {
  markTransport,
  useFinishTranscript,
  useMarks,
  useTranscript,
  type TranscriptReview,
} from './api';
import { currentLine } from './line';
import { MarkPanel } from './MarkPanel';
import { MarkList } from './MarkList';
import type { LocalMark, SavedMark } from './markSync';
import {
  extend,
  growFrom,
  markAt,
  MAX_MARK_WORDS,
  moveTo,
  rangeOf,
  reach,
  select,
  wouldPassLimit,
  type Range,
  type Selection,
} from './selection';
import { useMarkSync } from './useMarkSync';

export function TranscriptScreen({ session, progress }: { session: Session; progress: ReactNode }) {
  const transcript = useTranscript(session.id);
  const marks = useMarks(session.id);
  const code = transcript.error instanceof ApiError ? transcript.error.code : null;
  const waiting = code === 'transcript_not_ready';
  // Once the learner has waited, its arrival is announced politely (UX-04, UX-22). The
  // region stays mounted across both views so the change is heard.
  const [waited, setWaited] = useState(false);
  if (waiting && !waited) setWaited(true);
  const ready = Boolean(transcript.data && marks.data);
  return (
    <>
      {ready ? (
        <TranscriptWork
          key={session.id}
          session={session}
          progress={progress}
          data={transcript.data!}
          marks={marks.data!.marks}
        />
      ) : (
        <TranscriptPending
          session={session}
          progress={progress}
          transcript={transcript}
          marks={marks}
        />
      )}
      <p role="status" className="sr-only">
        {ready && waited ? 'Your transcript is ready.' : ''}
      </p>
    </>
  );
}

function TranscriptPending({
  session,
  progress,
  transcript,
  marks,
}: {
  session: Session;
  progress: ReactNode;
  transcript: ReturnType<typeof useTranscript>;
  marks: ReturnType<typeof useMarks>;
}) {
  const code = transcript.error instanceof ApiError ? transcript.error.code : null;
  const waiting = code === 'transcript_not_ready';
  const failed = code === 'transcript_failed';
  return (
    <Layout session={session} progress={progress} player={null}>
      {waiting ? (
        // Pending: what is happening, that nothing is lost, and that the page refreshes
        // itself (it polls and listens for transcript.ready); no invented estimate.
        <div
          role="status"
          aria-labelledby="transcript-pending"
          aria-busy="true"
          className="flex flex-col items-start gap-3 rounded-md border border-line bg-surface-raised p-4"
        >
          <p id="transcript-pending" className="flex items-center gap-2 font-bold">
            <span
              aria-hidden="true"
              className="size-4 animate-spin rounded-full border-2 border-line border-t-accent motion-reduce:animate-none"
            />
            Preparing your transcript…
          </p>
          <p>This page updates by itself when it is ready. Your progress is saved.</p>
          <button
            type="button"
            className={buttonClass('secondary')}
            onClick={() => void transcript.refetch()}
          >
            Check now
          </button>
        </div>
      ) : failed ? (
        <div className="flex flex-col items-start gap-3">
          <p role="alert">The transcript could not be prepared.</p>
          <p>Your progress is saved. Try again to check for an updated transcript.</p>
          <button
            type="button"
            className={buttonClass('secondary')}
            onClick={() => void transcript.refetch()}
          >
            Try again
          </button>
        </div>
      ) : transcript.isError ? (
        <ErrorPanel error={transcript.error} onRetry={() => void transcript.refetch()} />
      ) : marks.isError ? (
        <ErrorPanel error={marks.error} onRetry={() => void marks.refetch()} />
      ) : (
        <p role="status">Opening your Transcript…</p>
      )}
    </Layout>
  );
}

function Layout({
  session,
  progress,
  player,
  markList,
  aside,
  children,
}: {
  session: Session;
  progress: ReactNode;
  player: ReactNode;
  /** The transcript's own marks, once it is open, for the Dictation result to share. */
  markList?: OpenMarkList;
  /** The side panel: the mark list and keys beside the text from 1024 px, after it below. */
  aside?: ReactNode;
  children: ReactNode;
}) {
  const blindDone = session.steps.some((step) => step.step === 'blind' && step.status === 'done');
  return (
    <PracticeLayout
      heading={`Transcript: ${session.content_title}`}
      clipTitle={session.content_title}
      clipMeta={`Passage ${formatClock(session.passage.start_ms)} to ${formatClock(session.passage.end_ms)}`}
      back={{ to: '/library', label: 'Library' }}
      progress={progress}
      player={player}
      rule={STEP_RULES.transcript}
      workLabel="Transcript"
      aside={
        // The gist feedback (#69) first, then the keys and the mark list (#200).
        blindDone || aside ? (
          <>
            {blindDone && <TranscriptGistPanel sessionId={session.id} />}
            {aside}
          </>
        ) : undefined
      }
    >
      <p className="text-body-s">Transcript can't be skipped: it shows what you missed.</p>
      {session.steps.some((step) => step.step === 'dictation' && step.status === 'done') && (
        <DictationResultPanel sessionId={session.id} markList={markList} />
      )}
      {children}
    </PracticeLayout>
  );
}

function TranscriptWork({
  session,
  progress,
  data,
  marks,
}: {
  session: Session;
  progress: ReactNode;
  data: TranscriptReview;
  marks: SavedMark[];
}) {
  const audio = useRef<HTMLAudioElement>(null);
  const [replays, setReplays] = useState(0);
  const player = usePassagePlayer(audio, data.passage.start_ms, data.passage.end_ms);
  const line = currentLine(data.lines, data.passage.start_ms + player.positionMs);
  const jump = (absoluteMs: number) => {
    if (player.status !== 'ready') return; // words can be marked before the audio is ready
    player.seek(absoluteMs - data.passage.start_ms);
    if (audio.current?.paused) player.toggle();
  };
  const replayLine = () => {
    const target = line ?? data.lines[0];
    if (target) {
      jump(target.start_ms);
      setReplays((count) => count + 1);
    }
  };
  const controls = { ...player, replays, replay: replayLine };
  usePlayerKeys(controls);
  const marking = useMarking(session.id, data, marks, jump);
  const finish = useFinishTranscript(session.id);
  const finishReason = useRef<HTMLParagraphElement>(null);
  const finishStarted = useRef(false);
  const finishBlocked = !marking.saved || finish.isPending;
  return (
    <Layout
      session={session}
      progress={progress}
      markList={marking.markList}
      aside={
        <>
          <details className="rounded-md border border-line p-3">
            <summary className="cursor-pointer font-bold">Keyboard shortcuts</summary>
            <p className="mt-2 text-body-s">
              Space or K: play/pause. J: back 5 seconds. R: replay line. [ and ]: speed. Tab to a
              word, then Enter or Space to jump. On a word: Left and Right arrows move, Shift and an
              arrow select more words, M marks the selection or opens its note, Esc clears it. Use
              arrow keys on the seek bar.
            </p>
          </details>
          {marking.list}
        </>
      }
      player={
        <PassagePlayerControls
          audioRef={audio}
          player={controls}
          src={data.media_url}
          playerId="transcript"
          replayLabel="Replay line"
          replayDisabled={data.lines.length === 0}
          description={line ? `Line ${line.index + 1} of ${data.lines.length}` : 'Passage audio'}
          errorSuffix="Your progress is saved."
        />
      }
    >
      <h2 className="font-display text-heading">Listen with the transcript</h2>
      <p>Choose any word to hear it. Replay the current line as often as you like.</p>
      {marking.panel}
      {data.lines.length === 0 ? (
        <p>No speech was found in this passage.</p>
      ) : (
        <ol aria-label="Transcript lines" className="flex flex-col gap-3">
          {data.lines.map((item) => (
            <li
              key={item.index}
              aria-current={line?.index === item.index ? 'true' : undefined}
              className={`rounded-md border-l-4 p-3 ${line?.index === item.index ? 'border-accent bg-surface-sunken' : 'border-transparent'}`}
            >
              <span className="mb-1 block text-body-s font-bold">
                Line {item.index + 1}
                {line?.index === item.index && <span> · Current line</span>}
              </span>
              <p className="text-body-l [overflow-wrap:anywhere]">
                {item.words.map((word) => (
                  <span key={word.index}>
                    <button
                      type="button"
                      ref={(element) => {
                        marking.wordRefs.current[word.index] = element;
                      }}
                      aria-label={`Jump to ${word.text || 'removed word'}${word.edited ? ' (edited)' : ''}`}
                      aria-describedby={marking.describedBy(word.index)}
                      className={`min-h-11 max-w-full rounded-sm px-1 text-left underline decoration-dotted underline-offset-4 [overflow-wrap:anywhere] hover:bg-surface-raised ${marking.markClass(word.index)} ${marking.isSelected(word.index) ? 'outline-2 outline-mark-strong' : ''}`}
                      onClick={(event) => {
                        // Choosing a range (Shift+click) must not move the audio.
                        if (!marking.choose(word.index, event)) jump(word.start_ms);
                      }}
                      onKeyDown={(event) => marking.onWordKey(word.index, event)}
                    >
                      {word.text || '(removed word)'}
                      {word.edited && <span className="ml-1 text-body-s font-bold">Edited</span>}
                    </button>{' '}
                  </span>
                ))}
              </p>
            </li>
          ))}
        </ol>
      )}
      {finishBlocked && (
        <p id="finish-transcript-reason" ref={finishReason} tabIndex={-1}>
          {finish.isPending
            ? 'Finishing Transcript. Please wait.'
            : 'Wait for your marks to save before finishing.'}
        </p>
      )}
      {finish.isError && <ErrorPanel error={finish.error} />}
      <button
        type="button"
        className={buttonClass('primary', 'self-start')}
        aria-disabled={finishBlocked || undefined}
        aria-describedby={finishBlocked ? 'finish-transcript-reason' : undefined}
        onClick={() => {
          if (finishBlocked || finishStarted.current) finishReason.current?.focus();
          else {
            // Mutation notifications render asynchronously; guard rapid activation now.
            finishStarted.current = true;
            finish.mutate(undefined, {
              onSettled: () => {
                finishStarted.current = false;
              },
            });
          }
        }}
      >
        {finish.isPending ? 'Finishing Transcript…' : 'Finish Transcript'}
      </button>
    </Layout>
  );
}

const LIMIT_MESSAGE = `A mark covers at most ${MAX_MARK_WORDS} words.`;
const MARKED = 'mark-description-marked';
const FROM_DICTATION = 'mark-description-dictation';
const TO_CONFIRM = 'mark-description-suggested';
const SELECTED = 'mark-description-selected';

/** How a marked word shows its mark; a word in several marks shows the most pressing. */
type MarkKind = 'suggested' | 'dictation' | 'manual';
const KIND_ORDER: MarkKind[] = ['suggested', 'dictation', 'manual'];
const kindOf = (mark: LocalMark): MarkKind =>
  mark.status === 'suggested' ? 'suggested' : mark.source === 'dictation' ? 'dictation' : 'manual';
const KIND_DESCRIPTION: Record<MarkKind, string> = {
  suggested: TO_CONFIRM,
  dictation: FROM_DICTATION,
  manual: MARKED,
};
// FR-TR-3: Dictation marks carry a line under the word as well as the fill, dashed while
// they wait to be confirmed, so the source never rests on colour alone.
const KIND_CLASS: Record<MarkKind, string> = {
  suggested: 'bg-mark-bg border-b-2 border-dashed border-mark-strong',
  dictation: 'bg-mark-bg border-b-2 border-solid border-mark-strong',
  manual: 'bg-mark-bg',
};

function covers(range: Range, word: number): boolean {
  return range.word_from <= word && word <= range.word_to;
}

/**
 * Selecting words and marking them (#58; FR-TR-2, UI-4): a click or an arrow selects a
 * word (or the mark around it), Shift grows the selection, and the Mark button or the M
 * key marks it at once. `MarkSync` keeps the mark on this device and saves it.
 */
function useMarking(
  sessionId: string,
  data: TranscriptReview,
  saved: SavedMark[],
  jump: (atMs: number) => void,
) {
  const words = useMemo(() => data.lines.flatMap((line) => line.words), [data]);
  const sync = useMarkSync({
    storageKey: `listenup:marks:${sessionId}`,
    marks: saved,
    transport: markTransport(sessionId),
  });
  const [selection, setSelection] = useState<Selection | null>(null);
  const [announcement, setAnnouncement] = useState('');
  // The same words twice in a row would not change the live region, so a screen reader
  // would stay silent the second time: a trailing no-break space makes it a change.
  const announce = (text: string) =>
    setAnnouncement((previous) => (previous === text ? `${text}\u00a0` : text));
  const [focusNote, setFocusNote] = useState(false);
  const [removed, setRemoved] = useState<LocalMark | null>(null);
  const wordRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const marked = useMemo(() => {
    const kinds = new Map<number, MarkKind>();
    for (const mark of sync.marks) {
      const kind = kindOf(mark);
      for (let i = mark.word_from; i <= mark.word_to; i += 1) {
        const had = kinds.get(i);
        if (!had || KIND_ORDER.indexOf(kind) < KIND_ORDER.indexOf(had)) kinds.set(i, kind);
      }
    }
    return kinds;
  }, [sync.marks]);
  const range = selection ? rangeOf(selection) : null;
  const current = markAt(selection, sync.marks);
  const phraseOf = (r: Range) =>
    words
      .slice(r.word_from, r.word_to + 1)
      .map((word) => word.text)
      .filter(Boolean)
      .join(' ');
  const focusWord = (index: number) => wordRefs.current[index]?.focus();

  const mark = (target: Selection) => {
    const existing = markAt(target, sync.marks);
    if (existing) {
      setFocusNote(true);
      return;
    }
    const r = rangeOf(target);
    const phrase = phraseOf(r);
    if (!phrase) {
      announce('Removed words cannot be marked.'); // the API refuses them too
      return;
    }
    const at_ms = words[r.word_from]!.start_ms;
    sync.add({ id: crypto.randomUUID(), ...r, at_ms, note: null });
    announce(`Mark added: ${phrase}, ${formatClock(at_ms)}.`);
  };

  const onWordKey = (index: number, event: ReactKeyboardEvent) => {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    const held = selection && covers(rangeOf(selection), index) ? selection : null;
    if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
      event.preventDefault();
      const step = event.key === 'ArrowRight' ? 1 : -1;
      if (event.shiftKey) {
        // Grow from the word that has the focus, so the focus ring never jumps.
        const from = held ? growFrom(held, index) : select(index);
        const next = extend(from, step, words.length);
        if (wouldPassLimit(from, step)) announce(LIMIT_MESSAGE);
        setSelection(next);
        focusWord(next.focus);
      } else {
        const next = Math.min(words.length - 1, Math.max(0, index + step));
        setSelection(moveTo(next, sync.marks));
        focusWord(next);
      }
    } else if (event.key === 'm' || event.key === 'M') {
      event.preventDefault();
      const target = held ?? moveTo(index, sync.marks);
      setSelection(target);
      mark(target);
    } else if (event.key === 'Escape' && selection) {
      event.preventDefault();
      setSelection(null);
    }
  };

  /** Select the clicked word, or extend to it with Shift; true when the click extended. */
  const choose = (index: number, event: MouseEvent): boolean => {
    if (!(event.shiftKey && selection)) {
      setSelection(moveTo(index, sync.marks));
      return false;
    }
    const next = reach(selection, index);
    if (next.focus !== index) announce(LIMIT_MESSAGE);
    setSelection(next);
    return true;
  };

  const removeMark = (id: string) => {
    const mark = sync.marks.find((item) => item.id === id);
    if (!mark) return;
    setRemoved(mark);
    sync.remove(id);
    announce('Mark removed.');
    focusWord(mark.word_from);
  };

  const confirmMark = (id: string) => {
    const mark = sync.marks.find((item) => item.id === id);
    if (!mark || mark.status === 'confirmed') return;
    sync.confirm(id);
    announce(`Mark confirmed: ${phraseOf(mark) || 'removed words'}.`);
  };

  const onNoteFocused = useCallback(() => setFocusNote(false), []);

  const panel = (
    <>
      <span id={MARKED} hidden>
        Marked
      </span>
      <span id={FROM_DICTATION} hidden>
        Marked from Dictation
      </span>
      <span id={TO_CONFIRM} hidden>
        Marked from Dictation, to confirm
      </span>
      <span id={SELECTED} hidden>
        Selected
      </span>
      <MarkPanel
        selection={selection}
        phrase={range ? phraseOf(range) : ''}
        mark={current}
        wordCount={words.length}
        markCount={sync.marks.length}
        status={sync.status}
        announcement={announcement}
        focusNote={focusNote}
        onSelect={setSelection}
        onMark={() => {
          if (!selection) return;
          mark(selection);
          focusWord(selection.focus);
        }}
        onNote={sync.setNote}
        onConfirm={confirmMark}
        onRemove={removeMark}
        onNoteFocused={onNoteFocused}
      />
    </>
  );

  return {
    panel,
    saved: !sync.hasPendingChanges,
    list: (
      <>
        <MarkList
          marks={sync.marks}
          phraseOf={phraseOf}
          onPlay={(mark) => {
            setSelection({ anchor: mark.word_from, focus: mark.word_to });
            setFocusNote(false);
            jump(mark.at_ms);
          }}
          onEdit={(mark) => {
            setSelection({ anchor: mark.word_from, focus: mark.word_to });
            setFocusNote(true);
          }}
          onConfirm={(mark) => confirmMark(mark.id)}
          onRemove={(mark) => removeMark(mark.id)}
        />
        {removed && !sync.marks.some((mark) => mark.id === removed.id) && (
          <div className="flex flex-wrap items-center gap-2">
            <p>Mark removed. You can undo this removal.</p>
            <button
              type="button"
              className={buttonClass('secondary')}
              onClick={() => {
                sync.undoRemove(removed);
                setRemoved(null);
                announce('Mark restored.');
                focusWord(removed.word_from);
              }}
            >
              Undo
            </button>
          </div>
        )}
      </>
    ),
    wordRefs,
    onWordKey,
    choose,
    markClass: (index: number) => {
      const kind = marked.get(index);
      return kind ? KIND_CLASS[kind] : '';
    },
    isSelected: (index: number) => (range ? covers(range, index) : false),
    // Marks added from the Dictation result join this list, and words marked here show
    // as added there (#55): one list on the page, so the two never disagree.
    markList: { marks: sync.marks, take: sync.takeSaved } satisfies OpenMarkList,
    describedBy: (index: number) => {
      const kind = marked.get(index);
      if (kind) return KIND_DESCRIPTION[kind];
      return range && covers(range, index) ? SELECTED : undefined;
    },
  };
}

function usePlayerKeys(player: PassagePlayer) {
  useEffect(() => {
    const handle = (event: KeyboardEvent) => {
      const target = event.target;
      if (
        event.defaultPrevented ||
        event.repeat ||
        player.status !== 'ready' ||
        (target instanceof HTMLElement &&
          target.closest('button, input, select, textarea, a, summary, [contenteditable="true"]'))
      )
        return;
      const action = actionFor(event, false);
      if (!action) return;
      event.preventDefault();
      switch (action) {
        case 'toggle':
          player.toggle();
          break;
        case 'back':
          player.back();
          break;
        case 'replay':
          player.replay();
          break;
        case 'slower':
          player.setSpeed(stepSpeed(player.speed, 1));
          break;
        case 'faster':
          player.setSpeed(stepSpeed(player.speed, -1));
          break;
      }
    };
    document.addEventListener('keydown', handle);
    return () => document.removeEventListener('keydown', handle);
  }, [player]);
}
