import { useEffect, useId, useRef, useState, type FormEvent } from 'react';

import { buttonClass } from '../../components/button';
import { ErrorPanel } from '../../components/ErrorPanel';
import { AlertIcon, CheckIcon } from '../../components/icons';
import { useSubmitGist } from './api';
import { MAX_GIST_CHARS, MIN_SENTENCES, countSentences, sentenceStatus } from './gist';

const draftKey = (attemptId: string) => `listenup:blind-gist:${attemptId}`;

function readDraft(attemptId: string): string {
  try {
    return localStorage.getItem(draftKey(attemptId)) ?? '';
  } catch {
    return '';
  }
}

function writeDraft(attemptId: string, text: string): boolean {
  try {
    if (text) localStorage.setItem(draftKey(attemptId), text);
    else localStorage.removeItem(draftKey(attemptId));
    return true;
  } catch {
    return false;
  }
}

/**
 * The gist (FR-BL-4, #65; final UI D04): three sentences about what the learner heard,
 * shown only once the whole passage has played. The count updates as the learner
 * types; Submit stays focusable and says what is missing. The draft is kept on this
 * device, so leaving and coming back loses nothing.
 */
export function GistForm({ sessionId, attemptId }: { sessionId: string; attemptId: string }) {
  const [text, setText] = useState(() => readDraft(attemptId));
  const [saved, setSaved] = useState(false);
  const [tried, setTried] = useState(0);
  const box = useRef<HTMLTextAreaElement>(null);
  const message = useRef<HTMLParagraphElement>(null);
  const submit = useSubmitGist(sessionId, attemptId);
  const ids = { box: useId(), count: useId(), error: useId() };
  const count = countSentences(text);
  const ready = count >= MIN_SENTENCES && text.trim().length <= MAX_GIST_CHARS;

  useEffect(() => box.current?.focus(), []);
  // Submit pressed too early: move focus to the message, which is also announced.
  useEffect(() => {
    if (tried) message.current?.focus();
  }, [tried]);
  useEffect(() => {
    const timer = window.setTimeout(() => setSaved(writeDraft(attemptId, text)), 500);
    return () => window.clearTimeout(timer);
  }, [attemptId, text]);

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (submit.isPending) return;
    if (!ready) {
      setTried((n) => n + 1);
      return;
    }
    submit.mutate(text, { onSuccess: () => writeDraft(attemptId, '') });
  }

  const tooLong = text.trim().length > MAX_GIST_CHARS;
  return (
    <form className="flex flex-col gap-4" onSubmit={onSubmit} noValidate>
      <div className="flex flex-col gap-1">
        <h2 className="font-display text-title">What was it about?</h2>
        <p>
          Write three sentences: the main idea first, then the details you remember. Spelling and
          grammar don't count.
        </p>
      </div>
      <div className="flex flex-col gap-2">
        <label htmlFor={ids.box} className="font-bold">
          Your gist
        </label>
        <textarea
          id={ids.box}
          ref={box}
          value={text}
          onChange={(event) => {
            setText(event.target.value);
            setSaved(false);
          }}
          rows={8}
          spellCheck={false}
          autoComplete="off"
          autoCapitalize="off"
          autoCorrect="off"
          aria-describedby={`${ids.count}${tried > 0 && !ready ? ` ${ids.error}` : ''}`}
          aria-invalid={tried > 0 && !ready ? true : undefined}
          className="min-h-56 rounded-md border border-line-strong bg-surface-raised p-3 font-sans text-body"
        />
        <div className="flex flex-wrap items-center justify-between gap-2 text-body-s">
          <p id={ids.count} aria-live="polite" className={ready ? '' : 'font-bold text-accent'}>
            {tooLong
              ? `Keep it under ${MAX_GIST_CHARS} characters. Keep the main points.`
              : sentenceStatus(count)}
          </p>
          {saved && text && (
            <span className="inline-flex items-center gap-1 text-ink-muted">
              <CheckIcon className="size-4 text-success" />
              Draft saved
            </span>
          )}
        </div>
        {tried > 0 && !ready && (
          <p
            id={ids.error}
            ref={message}
            tabIndex={-1}
            role="alert"
            className="flex items-center gap-1 text-body-s font-bold text-danger"
          >
            <AlertIcon className="size-4" />
            {tooLong
              ? `The gist is over ${MAX_GIST_CHARS} characters. Shorten it, then submit.`
              : `${sentenceStatus(count).replace(/\.$/, '')}, then submit.`}
          </p>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="submit"
          className={buttonClass('primary')}
          aria-disabled={!ready || submit.isPending}
          aria-describedby={ids.count}
        >
          {submit.isPending ? 'Submitting…' : 'Submit gist'}
        </button>
        <p className="text-body-s text-ink-muted">
          A sentence ends with a full stop, question mark or exclamation mark, and has at least 3
          words.
        </p>
      </div>
      {submit.isError && <ErrorPanel error={submit.error} onRetry={() => submit.reset()} />}
    </form>
  );
}
