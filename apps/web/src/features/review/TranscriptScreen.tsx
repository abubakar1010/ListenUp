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
import { ApiError } from '../../api/client';
import { buttonClass } from '../../components/button';
import { ErrorPanel } from '../../components/ErrorPanel';
import { DictationResultPanel } from '../dictation/DictationResultPanel';
import { PassagePlayerControls } from '../media/PassagePlayerControls';
import { actionFor, stepSpeed } from '../media/playerPolicy';
import { usePassagePlayer, type PassagePlayer } from '../media/usePassagePlayer';
import type { Session } from '../session/api';
import { PracticeLayout } from '../session/PracticeLayout';
import { STEP_RULES } from '../session/plan';
import { formatClock } from '../session/time';
import { markTransport, useMarks, useTranscript, type TranscriptReview } from './api';
import { currentLine } from './line';
import { MarkPanel } from './MarkPanel';
import type { SavedMark } from './markSync';
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
  if (transcript.data && marks.data)
    return (
      <TranscriptWork
        key={session.id}
        session={session}
        progress={progress}
        data={transcript.data}
        marks={marks.data.marks}
      />
    );
  const code = transcript.error instanceof ApiError ? transcript.error.code : null;
  const waiting = code === 'transcript_not_ready';
  const failed = code === 'transcript_failed';
  return (
    <Layout session={session} progress={progress} player={null}>
      {waiting || failed ? (
        <div className="flex flex-col items-start gap-3">
          <p role={waiting ? 'status' : 'alert'}>
            {waiting ? 'Preparing your transcript…' : 'The transcript could not be prepared.'}
          </p>
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
  children,
}: {
  session: Session;
  progress: ReactNode;
  player: ReactNode;
  children: ReactNode;
}) {
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
    >
      <p className="text-body-s">Transcript can't be skipped: it shows what you missed.</p>
      {session.steps.some((step) => step.step === 'dictation' && step.status === 'done') && (
        <DictationResultPanel sessionId={session.id} />
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
  const marking = useMarking(session.id, data, marks);
  return (
    <Layout
      session={session}
      progress={progress}
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
      <details className="rounded-md border border-line p-3">
        <summary className="cursor-pointer font-bold">Keyboard shortcuts</summary>
        <p className="mt-2 text-body-s">
          Space or K: play/pause. J: back 5 seconds. R: replay line. [ and ]: speed. Tab to a word,
          then Enter or Space to jump. On a word: Left and Right arrows move, Shift and an arrow
          select more words, M marks the selection or opens its note, Esc clears it. Use arrow keys
          on the seek bar.
        </p>
      </details>
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
                      className={`min-h-11 max-w-full rounded-sm px-1 text-left underline decoration-dotted underline-offset-4 [overflow-wrap:anywhere] hover:bg-surface-raised ${marking.isMarked(word.index) ? 'bg-mark-bg' : ''} ${marking.isSelected(word.index) ? 'outline-2 outline-mark-strong' : ''}`}
                      onClick={(event) => {
                        marking.choose(word.index, event);
                        jump(word.start_ms);
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
    </Layout>
  );
}

const LIMIT_MESSAGE = `A mark covers at most ${MAX_MARK_WORDS} words.`;
const MARKED = 'mark-description-marked';
const SELECTED = 'mark-description-selected';

function covers(range: Range, word: number): boolean {
  return range.word_from <= word && word <= range.word_to;
}

/**
 * Selecting words and marking them (#58; FR-TR-2, UI-4): a click or an arrow selects a
 * word (or the mark around it), Shift grows the selection, and the Mark button or the M
 * key marks it at once. `MarkSync` keeps the mark on this device and saves it.
 */
function useMarking(sessionId: string, data: TranscriptReview, saved: SavedMark[]) {
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
  const wordRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const marked = useMemo(() => {
    const indices = new Set<number>();
    for (const mark of sync.marks)
      for (let i = mark.word_from; i <= mark.word_to; i += 1) indices.add(i);
    return indices;
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

  const choose = (index: number, event: MouseEvent) => {
    if (!(event.shiftKey && selection)) {
      setSelection(moveTo(index, sync.marks));
      return;
    }
    const next = reach(selection, index);
    if (next.focus !== index) announce(LIMIT_MESSAGE);
    setSelection(next);
  };

  const onNoteFocused = useCallback(() => setFocusNote(false), []);

  const panel = (
    <>
      <span id={MARKED} hidden>
        Marked
      </span>
      <span id={SELECTED} hidden>
        Selected
      </span>
      <MarkPanel
        selection={selection}
        phrase={range ? phraseOf(range) : ''}
        mark={current}
        wordCount={words.length}
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
        onRemove={(id) => {
          sync.remove(id);
          announce('Mark removed.');
          if (selection) focusWord(selection.focus);
        }}
        onNoteFocused={onNoteFocused}
      />
    </>
  );

  return {
    panel,
    wordRefs,
    onWordKey,
    choose,
    isMarked: (index: number) => marked.has(index),
    isSelected: (index: number) => (range ? covers(range, index) : false),
    describedBy: (index: number) =>
      marked.has(index) ? MARKED : range && covers(range, index) ? SELECTED : undefined,
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
