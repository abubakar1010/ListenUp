import { useRef, useState } from 'react';

import { ErrorPanel } from '../../components/ErrorPanel';
import { useFocusLater } from '../../lib/useFocusLater';
import { useContent } from '../content/useContent';
import type { Session } from '../session/api';
import { useRounds } from './api';
import { DeleteRecording } from './DeleteRecording';
import { RoundFeedback } from './RoundFeedback';

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
      {rounds.data?.rounds
        .filter((round) => round.recorded_at)
        .map((round) => (
          <section
            key={round.id}
            aria-label={
              round.recording_available ? `Round ${round.round} replay` : `Round ${round.round}`
            }
          >
            <h2 className="font-display text-body">Round {round.round}</h2>
            {round.recording_available && content.data?.media_url && (
              <audio
                controls
                preload="none"
                aria-label={`Original, round ${round.round} segment`}
                src={`${content.data.media_url}#t=${rounds.data!.segment.start_ms / 1000},${rounds.data!.segment.end_ms / 1000}`}
              />
            )}
            {round.recording_available && (
              <audio
                controls
                preload="none"
                aria-label={`Your recording of round ${round.round}`}
                src={`/api/v1/shadow/rounds/${round.id}/recording`}
              />
            )}
            {/* Grades and word labels outlive the recording (D7). */}
            <RoundFeedback roundId={round.id} round={round.round} showMarkers headingLevel={3} />
            {round.recording_available && (
              <DeleteRecording
                sessionId={session.id}
                roundId={round.id}
                round={round.round}
                onDeleted={(message) => {
                  setStatus(message);
                  focusRegion();
                }}
              />
            )}
          </section>
        ))}
      {rounds.isError && <ErrorPanel error={rounds.error} onRetry={() => void rounds.refetch()} />}
      {content.isError && (
        <ErrorPanel error={content.error} onRetry={() => void content.refetch()} />
      )}
    </section>
  );
}
