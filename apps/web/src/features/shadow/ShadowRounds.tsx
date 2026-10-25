import { useCallback, useEffect, useRef } from 'react';
import { buttonClass } from '../../components/button';
import { BusyButton } from '../../components/BusyButton';
import { ErrorPanel } from '../../components/ErrorPanel';
import { useContent } from '../content/useContent';
import { useChangeRound, useRounds } from './api';
import { ShadowRoundPlayer } from './ShadowRoundPlayer';

export function ShadowRounds({
  sessionId,
  contentId,
  selectionPending = false,
}: {
  sessionId: string;
  contentId: string;
  selectionPending?: boolean;
}) {
  const state = useRounds(sessionId);
  const change = useChangeRound(sessionId);
  const content = useContent(contentId);
  const mutateRound = change.mutate;
  const current = state.data?.current;
  const number = current?.round ?? 0;
  const heading = useRef<HTMLHeadingElement>(null);
  const focusRound = useRef(false);
  useEffect(() => {
    if (focusRound.current && number) {
      heading.current?.focus();
      focusRound.current = false;
    }
  }, [number]);
  const end = useCallback(() => {
    mutateRound({ number, action: 'playback-ended' });
  }, [mutateRound, number]);
  if (!state.data)
    return state.isError ? (
      <ErrorPanel error={state.error} onRetry={() => void state.refetch()} />
    ) : (
      <p role="status">Loading rounds…</p>
    );
  const ended = current?.playback_status === 'ended';
  return (
    <section
      aria-label="Shadow rounds"
      className="flex min-w-0 flex-col gap-4 rounded-md border border-line bg-surface-raised p-4 md:p-6"
    >
      <h2 ref={heading} tabIndex={-1} className="font-display text-heading">
        {number ? `Round ${number} of 3` : 'Three Shadow rounds'}
      </h2>
      <ol aria-label="Round status" className="flex flex-wrap gap-4">
        {[1, 2, 3].map((n) => (
          <li key={n} aria-current={n === number ? 'step' : undefined}>
            Round {n}:{' '}
            {state.data.rounds.find((r) => r.round === n)?.playback_status === 'ended'
              ? 'playback ended'
              : n === number
                ? 'current'
                : 'not started'}
          </li>
        ))}
      </ol>
      <p>
        Three rounds at original speed, each with a short count-in. Read the transcript in round 1;
        shadow without it in rounds 2 and 3.
      </p>
      {number === 1 &&
      current?.transcript_shown &&
      !change.isPending &&
      !state.isFetching &&
      state.data.text !== undefined ? (
        <p aria-label="Segment transcript">{state.data.text}</p>
      ) : number > 1 ? (
        <p>Transcript hidden for this round.</p>
      ) : null}
      {current && !ended && content.data?.media_url && (
        <ShadowRoundPlayer
          key={number}
          number={number}
          src={content.data.media_url}
          startMs={state.data.segment.start_ms}
          endMs={state.data.segment.end_ms}
          onEnded={end}
        />
      )}
      {ended && <p role="status">Playback ended. Feedback unavailable.</p>}
      <p>No recording has been saved. Playback alone does not complete Shadow.</p>
      {selectionPending && <p>Save your segment before starting a round.</p>}
      {(!current || ended) && number < 3 && (
        <BusyButton
          type="button"
          className={buttonClass('primary', 'self-start')}
          busy={change.isPending || state.isFetching || selectionPending}
          onClick={() => {
            if (selectionPending) return;
            focusRound.current = true;
            change.mutate({ number: number + 1, action: 'start' });
          }}
        >
          Start round {number + 1}
        </BusyButton>
      )}
      {number === 3 && ended && (
        <p>All three playbacks have ended. Recording and plan completion are not available yet.</p>
      )}
      {change.isError && (
        <ErrorPanel
          error={change.error}
          onRetry={() => {
            if (change.variables) change.mutate(change.variables);
          }}
        />
      )}
      {state.isError && <ErrorPanel error={state.error} onRetry={() => void state.refetch()} />}
      {content.isError && (
        <ErrorPanel error={content.error} onRetry={() => void content.refetch()} />
      )}
    </section>
  );
}
