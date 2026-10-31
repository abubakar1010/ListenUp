import { useState } from 'react';

import { buttonClass } from '../../components/button';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { ErrorPanel } from '../../components/ErrorPanel';
import { useDeleteRecording } from './api';

/**
 * "Delete recording" beside a round's replay, after confirmation (FR-SH-17). The
 * caller announces `onDeleted` in its status region; the replay then disappears.
 */
export function DeleteRecording({
  sessionId,
  roundId,
  round,
  onDeleted,
}: {
  sessionId: string;
  roundId: string;
  round: number;
  onDeleted: (message: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const deletion = useDeleteRecording(sessionId);
  function confirm() {
    deletion.mutate(roundId, {
      onSuccess: () => {
        setOpen(false);
        onDeleted(`Recording of round ${round} deleted.`);
      },
    });
  }
  return (
    <>
      <button
        type="button"
        className={buttonClass('secondary', 'self-start')}
        onClick={() => {
          deletion.reset();
          setOpen(true);
        }}
      >
        Delete recording <span className="sr-only">of round {round}</span>
      </button>
      {open && (
        <ConfirmDialog
          title={`Delete your recording of round ${round}?`}
          confirmLabel="Delete recording"
          cancelLabel="Keep recording"
          onConfirm={confirm}
          onCancel={() => setOpen(false)}
          busy={deletion.isPending}
          busyLabel="Deleting recording…"
          footer={
            deletion.isError ? <ErrorPanel error={deletion.error} onRetry={confirm} /> : undefined
          }
        >
          <p>
            The recording is deleted for good and cannot be replayed. The round keeps its place in
            the plan and any scores.
          </p>
        </ConfirmDialog>
      )}
    </>
  );
}
