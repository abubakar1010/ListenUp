import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';

import { buttonClass } from '../../components/button';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { ErrorPanel } from '../../components/ErrorPanel';
import { SaveStatus, saveStatusText, useAutosave } from '../../lib/autosave';
import type { Session } from '../session/api';
import { PracticeLayout } from '../session/PracticeLayout';
import { STEP_RULES } from '../session/plan';
import { formatClock } from '../session/time';
import {
  MAX_DRAFT_CHARS,
  draftStorageKey,
  recordListenStarted,
  saveDraft,
  useDictationAttempt,
  useSubmitDictation,
  type DictationAttempt,
} from './api';
import { DictationPlayer } from './DictationPlayer';
import { actionFor, stepSpeed, type PlayerAction } from './policy';
import { usePassagePlayer, type PassagePlayer } from './usePassagePlayer';

interface DictationScreenProps {
  session: Session;
  /** The plan's progress, with "Change entry", from the session page. */
  progress: ReactNode;
}

/**
 * The Dictation step (#51, #52; design E01): the passage player, one text area with an
 * autosaved draft, and no transcript, hints or suggestions anywhere (FR-DI-1 to
 * FR-DI-4, FR-TX-5). Coming back resumes the attempt and its draft (FR-PL-6).
 * Submitting (#54) completes the step; the diff follows on the session page.
 */
export function DictationScreen({ session, progress }: DictationScreenProps) {
  const attempt = useDictationAttempt(session.id);
  if (attempt.isSuccess) {
    return (
      <DictationWork
        key={attempt.data.id}
        session={session}
        attempt={attempt.data}
        progress={progress}
      />
    );
  }
  return (
    <Layout session={session} progress={progress} player={null}>
      {attempt.isError ? (
        <ErrorPanel error={attempt.error} onRetry={() => void attempt.refetch()} />
      ) : (
        <p role="status" className="text-ink-muted">
          Opening your Dictation…
        </p>
      )}
    </Layout>
  );
}

function Layout({
  session,
  progress,
  player,
  status,
  aside,
  children,
}: {
  session: Session;
  progress: ReactNode;
  player: ReactNode;
  status?: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
}) {
  return (
    <PracticeLayout
      heading={`Dictation: ${session.content_title}`}
      clipTitle={session.content_title}
      clipMeta={`Passage ${formatClock(session.passage.start_ms)} to ${formatClock(session.passage.end_ms)}`}
      back={{ to: '/library', label: 'Library' }}
      status={status}
      progress={progress}
      player={player}
      rule={STEP_RULES.dictation}
      workLabel="Dictation"
      aside={aside}
    >
      {children}
    </PracticeLayout>
  );
}

function wordCount(text: string): number {
  return text.split(/\s+/).filter(Boolean).length;
}

function DictationWork({
  session,
  attempt,
  progress,
}: {
  session: Session;
  attempt: DictationAttempt;
  progress: ReactNode;
}) {
  const draft = useAutosave<string>({
    storageKey: draftStorageKey(attempt.id),
    value: attempt.draft_text,
    version: attempt.draft_version,
    save: (text, version) => saveDraft(attempt.id, text, version),
  });
  const audio = useRef<HTMLAudioElement>(null);
  const listenRecorded = useRef(false);
  const listenRecording = useRef(false);
  const recordFirstPlay = useCallback(() => {
    if (listenRecorded.current || listenRecording.current) return;
    listenRecording.current = true;
    void recordListenStarted(attempt.id)
      .then(() => {
        listenRecorded.current = true;
      })
      .catch(() => undefined)
      .finally(() => {
        listenRecording.current = false;
      });
  }, [attempt.id]);
  const player = usePassagePlayer(
    audio,
    attempt.passage.start_ms,
    attempt.passage.end_ms,
    recordFirstPlay,
  );
  const submit = useSubmitDictation(session.id, attempt.id);
  const submitted = submit.isSuccess;
  const { discard } = draft;
  // The answer is final: no autosave may follow the submit, and the device copy is spent.
  useEffect(() => {
    if (submitted) discard();
  }, [submitted, discard]);
  const textArea = useRef<HTMLTextAreaElement>(null);
  const [announcement, setAnnouncement] = useState('');
  const [confirming, setConfirming] = useState(false);
  const noTextReason = useRef<HTMLParagraphElement>(null);

  useEffect(() => textArea.current?.focus(), []);
  usePlayerKeys(player, textArea);

  // Problems are announced as they happen; routine saves are not (design E01).
  const statusKind = draft.status.kind;
  const problemText =
    statusKind === 'offline' || statusKind === 'conflict' || statusKind === 'failed'
      ? saveStatusText(draft.status)
      : '';

  const words = wordCount(draft.value);
  const empty = words === 0;
  const busy = submit.isPending;
  const unavailable = empty || busy || submitted;

  // Submit stays focusable when it cannot act, and says why (UX-10).
  function onSubmitPress() {
    if (busy || submitted) return;
    if (empty) {
      noTextReason.current?.focus();
      return;
    }
    setConfirming(true);
  }

  function onConfirm() {
    setConfirming(false);
    submit.mutate({
      text: draft.value,
      version: session.version,
      replayCount: player.replays,
    });
  }

  return (
    <Layout
      session={session}
      progress={progress}
      status={<SaveStatus status={draft.status} />}
      player={<DictationPlayer audioRef={audio} player={player} src={attempt.media_url} />}
      aside={<KeysPanel />}
    >
      {draft.status.kind === 'conflict' && (
        <ConflictPanel
          theirs={draft.status.theirs}
          onKeepMine={draft.keepMine}
          onTakeTheirs={draft.takeTheirs}
        />
      )}
      {draft.restored && draft.status.kind !== 'conflict' && (
        <p className="text-body-s text-ink-muted">
          We restored text you typed earlier on this device that had not been saved yet.
        </p>
      )}
      <div className="flex flex-col gap-2">
        <label htmlFor="dictation-text" className="font-bold">
          Your text
        </label>
        <textarea
          ref={textArea}
          id="dictation-text"
          name="dictation-text"
          className="min-h-72 w-full rounded-md border border-line-strong bg-surface-raised p-3 text-body-l"
          value={draft.value}
          readOnly={submitted}
          maxLength={MAX_DRAFT_CHARS}
          spellCheck={false}
          autoComplete="off"
          autoCorrect="off"
          autoCapitalize="off"
          data-gramm="false"
          data-gramm_editor="false"
          data-enable-grammarly="false"
          aria-describedby="dictation-text-help"
          onChange={(event) => draft.update(event.target.value)}
          onBlur={() => {
            draft.flush();
            setAnnouncement(
              `${words} ${words === 1 ? 'word' : 'words'}. ${saveStatusText(draft.status)}`,
            );
          }}
        />
        <div className="flex flex-wrap justify-between gap-2 text-body-s text-ink-muted">
          <span id="dictation-text-help">
            <b className="font-mono text-ink">{words}</b> {words === 1 ? 'word' : 'words'} · spell
            check is off here, on purpose
          </span>
          <SaveStatus status={draft.status} />
        </div>
      </div>
      <div className="flex flex-col items-start gap-2">
        <button
          type="button"
          className={buttonClass('primary')}
          disabled={submitted}
          aria-disabled={unavailable}
          aria-busy={busy}
          aria-describedby={empty ? 'dictation-submit-reason' : undefined}
          onClick={onSubmitPress}
        >
          {busy ? 'Submitting…' : submitted ? 'Submitted' : 'Submit for scoring'}
        </button>
        {empty && (
          <p
            id="dictation-submit-reason"
            ref={noTextReason}
            tabIndex={-1}
            className="text-body-s font-bold text-ink"
          >
            Type at least one word to submit.
          </p>
        )}
        <p className="text-body-s text-ink-muted">
          Submitting ends this step and shows what you missed. Your text is saved as you go, here
          and on any browser you sign in on.
        </p>
        {submit.isError && <ErrorPanel error={submit.error} />}
      </div>
      {confirming && (
        <ConfirmDialog
          title="Submit your Dictation?"
          confirmLabel="Submit"
          cancelLabel="Keep typing"
          onConfirm={onConfirm}
          onCancel={() => setConfirming(false)}
        >
          <p>
            You typed {words} {words === 1 ? 'word' : 'words'}. After you submit, the text
            can&apos;t change and you see what you missed.
          </p>
        </ConfirmDialog>
      )}
      <p role="status" aria-live="polite" className="sr-only">
        {problemText || announcement}
      </p>
    </Layout>
  );
}

/** Space, K, J, R, [ and ] outside the text area; Esc and Ctrl+Alt chords inside it. */
function usePlayerKeys(
  player: PassagePlayer,
  textArea: React.RefObject<HTMLTextAreaElement | null>,
) {
  const latest = useRef(player);
  useEffect(() => {
    latest.current = player;
  });
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.repeat) return;
      const target = event.target as HTMLElement | null;
      // No player key acts while a dialog is open (UX-07).
      if (target?.closest?.('[role="dialog"]')) return;
      const inTextArea = target === textArea.current;
      const chord = event.ctrlKey && event.altKey;
      // Other controls keep their own keys (Space presses a button, letters pick options).
      const onControl =
        !inTextArea &&
        !!target?.closest?.('input, textarea, select, button, a[href], [contenteditable="true"]');
      if (onControl && !chord) return;
      const action = actionFor(event, inTextArea);
      if (!action) return;
      event.preventDefault();
      run(latest.current, action);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [textArea]);
}

function run(player: PassagePlayer, action: PlayerAction) {
  if (player.status !== 'ready') return;
  if (action === 'toggle') player.toggle();
  else if (action === 'back') player.back();
  else if (action === 'replay') player.replay();
  else if (action === 'slower') player.setSpeed(stepSpeed(player.speed, 1));
  else player.setSpeed(stepSpeed(player.speed, -1));
}

function ConflictPanel({
  theirs,
  onKeepMine,
  onTakeTheirs,
}: {
  theirs: string;
  onKeepMine: () => void;
  onTakeTheirs: () => void;
}) {
  return (
    <div
      role="alert"
      className="flex flex-col gap-3 rounded-md border-2 border-warning bg-surface-raised p-4"
    >
      <h2 className="font-display text-heading">Your text was changed in another tab</h2>
      <p>
        Another tab or browser saved a different version while this page was open. Nothing is saved
        here until you choose which text to keep.
      </p>
      <details>
        <summary className="cursor-pointer font-bold">See the other version</summary>
        <p className="mt-2 max-h-48 overflow-auto rounded-sm bg-surface-sunken p-3 whitespace-pre-wrap">
          {theirs || '(empty)'}
        </p>
      </details>
      <div className="flex flex-wrap gap-3">
        <button type="button" className={buttonClass('primary')} onClick={onKeepMine}>
          Keep the text on this page
        </button>
        <button type="button" className={buttonClass('secondary')} onClick={onTakeTheirs}>
          Use the other version
        </button>
      </div>
    </div>
  );
}

function KeysPanel() {
  const rows: [string, string[]][] = [
    ['Play or pause', ['Esc']],
    ['Back 5 s', ['Ctrl', 'Alt', 'J']],
    ['Replay segment', ['Ctrl', 'Alt', 'R']],
    ['Slower, faster', ['Ctrl', 'Alt', '[', ']']],
  ];
  return (
    <>
      <section
        aria-labelledby="dictation-keys"
        className="flex flex-col gap-2 rounded-md border border-line bg-surface-raised p-4"
      >
        <h2 id="dictation-keys" className="font-display text-heading">
          Keys
        </h2>
        <table className="text-body-s">
          <tbody>
            {rows.map(([name, keys]) => (
              <tr key={name}>
                <td className="py-1 pr-3">{name}</td>
                <td className="py-1">
                  {keys.map((key) => (
                    <kbd
                      key={key}
                      className="mr-1 rounded-sm border border-line-strong px-1 font-mono text-mono"
                    >
                      {key}
                    </kbd>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="text-body-s text-ink-muted">
          While typing. On a Mac: Ctrl and Option. Outside the text box: Space or K, J, R, [ and ].
        </p>
      </section>
      <div className="flex flex-col gap-1 rounded-md bg-surface-sunken p-4">
        <b>Why no text?</b>
        <span className="text-body-s">
          Dictation trains you to hear every sound, without guessing from the words around it. Slow
          down to 0.75x if a part is too fast.
        </span>
      </div>
    </>
  );
}
