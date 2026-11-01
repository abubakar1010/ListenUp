import { useRef, useState } from 'react';

import { ErrorPanel } from '../../components/ErrorPanel';
import { useFocusLater } from '../../lib/useFocusLater';
import { useContent } from '../content/useContent';
import type { Session } from '../session/api';
import { useRounds } from './api';
import { DeleteRecording } from './DeleteRecording';

/** Recorded rounds remain replayable after the plan completes (FR-SH-6/8/16). */
export function ShadowCompletion({ session }: { session: Session }) {
  const rounds = useRounds(session.id);
  const content = useContent(session.content_id);
  const [status, setStatus] = useState('');
  const region = useRef<HTMLElement>(null);
  const focusRegion = useFocusLater(region);
  return (
    <section
      ref={region}
      tabIndex={-1}
      aria-label="Shadow complete"
      className="flex w-full flex-col gap-3"
    >
      <p>Three Shadow rounds recorded.</p>
      <p role="status">{status}</p>
      <p>Feedback unavailable.</p>
      {rounds.data?.rounds
        .filter((round) => round.recording_available)
        .map((round) => (
          <section key={round.id} aria-label={`Round ${round.round} replay`}>
            <h2 className="font-display text-body">Round {round.round}</h2>
            {content.data?.media_url && (
              <audio
                controls
                preload="none"
                aria-label={`Original, round ${round.round} segment`}
                src={`${content.data.media_url}#t=${rounds.data!.segment.start_ms / 1000},${rounds.data!.segment.end_ms / 1000}`}
              />
            )}
            <audio
              controls
              preload="none"
              aria-label={`Your recording of round ${round.round}`}
              src={`/api/v1/shadow/rounds/${round.id}/recording`}
            />
            <DeleteRecording
              sessionId={session.id}
              roundId={round.id}
              round={round.round}
              onDeleted={(message) => {
                setStatus(message);
                focusRegion();
              }}
            />
          </section>
        ))}
      {rounds.isError && <ErrorPanel error={rounds.error} onRetry={() => void rounds.refetch()} />}
      {content.isError && (
        <ErrorPanel error={content.error} onRetry={() => void content.refetch()} />
      )}
    </section>
  );
}
