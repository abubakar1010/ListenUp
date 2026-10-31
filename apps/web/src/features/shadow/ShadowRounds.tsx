import { useCallback, useEffect, useRef, useState } from 'react';
import { buttonClass } from '../../components/button';
import { BusyButton } from '../../components/BusyButton';
import { ErrorPanel } from '../../components/ErrorPanel';
import { useContent } from '../content/useContent';
import { RECORDING_MAX_BYTES, useChangeRound, useRounds, useUploadRecording } from './api';
import { useFocusLater } from '../../lib/useFocusLater';
import { DeleteRecording } from './DeleteRecording';
import { useRoundRecorder, type Recording } from './recording';
import { ShadowReadiness } from './ShadowReadiness';
import { ShadowRoundPlayer } from './ShadowRoundPlayer';

export function ShadowRounds({
  sessionId,
  contentId,
  selectionPending = false,
  onStatus,
}: {
  sessionId: string;
  contentId: string;
  selectionPending?: boolean;
  onStatus?: (message: string) => void;
}) {
  const [status, setStatus] = useState('Loading rounds…');
  const reportStatus = onStatus ?? setStatus;
  const [ready, setReady] = useState(false);
  const state = useRounds(sessionId);
  const change = useChangeRound(sessionId);
  const content = useContent(contentId);
  const mutateRound = change.mutate;
  const current = state.data?.current;
  const number = current?.round ?? 0;
  const heading = useRef<HTMLHeadingElement>(null);
  const focusRound = useRef(false);
  const focusHeading = useFocusLater(heading);
  useEffect(() => {
    if (focusRound.current && number) {
      heading.current?.focus();
      focusRound.current = false;
    }
  }, [number]);
  const recorder = useRoundRecorder();
  const upload = useUploadRecording(sessionId);
  const uploadRecording = upload.mutate;
  const [held, setHeld] = useState<{ number: number; recording: Recording } | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const uploading = useRef<number | null>(null);
  const { begin, finish, cancel } = recorder;
  const countIn = useCallback(() => {
    setHeld(null);
    setNote(null);
    uploading.current = null;
    void begin().then((result) => {
      if (result === 'unavailable')
        setNote('This browser cannot record, so this round is not saved.');
    });
  }, [begin]);
  const stopped = useCallback(() => {
    cancel();
  }, [cancel]);
  const end = useCallback(() => {
    void finish().then((recording) => {
      if (recording && recording.blob.size > RECORDING_MAX_BYTES) {
        setNote('This recording is too large to save.');
      } else if (recording) setHeld({ number, recording });
      mutateRound({ number, action: 'playback-ended' });
    });
  }, [finish, mutateRound, number]);
  const ended0 = current?.playback_status === 'ended';
  const recorded = current?.recording_available === true;
  // The upload starts once the server has the playback end; a retry reuses the held blob.
  useEffect(() => {
    if (held && !recorded && ended0 && held.number === number && uploading.current !== number) {
      uploading.current = number;
      uploadRecording({ number, recording: held.recording });
    }
  }, [held, recorded, ended0, number, uploadRecording]);
  useEffect(() => {
    if (upload.isSuccess) reportStatus(`Recording saved for round ${number}.`);
    else if (upload.isPending) reportStatus(`Saving the recording of round ${number}…`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [upload.isSuccess, upload.isPending]);
  if (!state.data)
    return state.isError ? (
      <ErrorPanel error={state.error} onRetry={() => void state.refetch()} />
    ) : (
      <p role={onStatus ? undefined : 'status'}>Loading rounds…</p>
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
        {[1, 2, 3].map((n) => {
          const row = state.data.rounds.find((r) => r.round === n);
          return (
            <li key={n} aria-current={n === number ? 'step' : undefined}>
              Round {n}:{' '}
              {row?.recorded_at
                ? row.recording_available
                  ? 'recorded'
                  : 'recorded, recording deleted'
                : row?.playback_status === 'ended'
                  ? 'playback ended'
                  : n === number
                    ? 'current'
                    : 'not started'}
            </li>
          );
        })}
      </ol>
      <p>
        Three rounds at original speed, each with a short count-in. Read the transcript in round 1;
        shadow without it in rounds 2 and 3.
      </p>
      {!onStatus && <p role="status">{status}</p>}
      <ShadowReadiness onReady={setReady} onStatus={reportStatus} />
      <p>Tab to a control; press Enter or Space to activate it.</p>
      {number === 1 &&
      current?.transcript_shown &&
      !change.isPending &&
      !state.isFetching &&
      !state.isError &&
      state.data.text !== undefined ? (
        <p aria-label="Segment transcript">{state.data.text}</p>
      ) : number > 1 ? (
        <p>Transcript hidden for this round.</p>
      ) : null}
      {ready && current && !ended && content.data?.media_url && (
        <ShadowRoundPlayer
          key={number}
          number={number}
          src={content.data.media_url}
          startMs={state.data.segment.start_ms}
          endMs={state.data.segment.end_ms}
          onEnded={end}
          onCountIn={countIn}
          onStopped={stopped}
          onStatus={reportStatus}
        />
      )}
      {ended && <p>Playback ended.</p>}
      {note && <p>{note}</p>}
      {held && !recorded && upload.isError && (
        <div role="alert" className="flex flex-col gap-2">
          <p>Your recording did not upload. It is still here; nothing needs recording again.</p>
          <BusyButton
            type="button"
            className={buttonClass('secondary', 'self-start')}
            busy={upload.isPending}
            onClick={() => uploadRecording({ number: held.number, recording: held.recording })}
          >
            Retry upload
          </BusyButton>
        </div>
      )}
      <p>
        Each round is recorded from the count-in to the end of the segment and saved privately to
        your account. Playback alone does not complete Shadow.
      </p>
      {state.data.rounds
        .filter((r) => r.recording_available && content.data?.media_url)
        .map((r) => (
          <section
            key={r.round}
            aria-label={`Round ${r.round} replay`}
            className="flex flex-col gap-2"
          >
            <h3 className="font-display text-body">Round {r.round}: compare</h3>
            <audio
              controls
              preload="none"
              aria-label={`Original, round ${r.round} segment`}
              src={`${content.data?.media_url}#t=${state.data.segment.start_ms / 1000},${state.data.segment.end_ms / 1000}`}
            />
            <audio
              controls
              preload="none"
              aria-label={`Your recording of round ${r.round}`}
              src={`/api/v1/shadow/rounds/${r.id}/recording`}
            />
            {r.feedback === 'unavailable' && <p>Feedback unavailable.</p>}
            <DeleteRecording
              sessionId={sessionId}
              roundId={r.id}
              round={r.round}
              onDeleted={(message) => {
                reportStatus(message);
                focusHeading();
              }}
            />
          </section>
        ))}
      {selectionPending && <p>Save your segment before starting a round.</p>}
      {(!current || ended) && number < 3 && (
        <BusyButton
          type="button"
          className={buttonClass('primary', 'self-start')}
          busy={change.isPending || state.isFetching || upload.isPending}
          aria-disabled={selectionPending || !ready || undefined}
          onClick={() => {
            if (selectionPending || !ready) return;
            focusRound.current = true;
            change.mutate({ number: number + 1, action: 'start' });
          }}
        >
          Start round {number + 1}
        </BusyButton>
      )}
      {number === 3 && ended && (
        <p>
          Three playbacks ended. Shadow completes when all three recordings are saved. A round that
          was played but not saved cannot be recorded again, so Shadow does not complete until all
          three recordings are saved; you can skip Shadow to finish the plan.
        </p>
      )}
      {change.isError && (
        <ErrorPanel
          error={change.error}
          onRetry={() => {
            if (change.variables && (ready || change.variables.action === 'playback-ended'))
              change.mutate(change.variables);
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
