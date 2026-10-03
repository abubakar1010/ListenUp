import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useId, useRef, useState, type DragEvent } from 'react';
import { Link, useNavigate } from 'react-router';

import { usePageTitle } from '../../app/usePageTitle';
import { buttonClass } from '../../components/button';
import { ErrorPanel } from '../../components/ErrorPanel';
import { AlertIcon, BackIcon } from '../../components/icons';
import { ACCEPT_ATTRIBUTE, ACCEPTED_NAMES, checkFile, formatSize, type FileProblem } from './files';
import { checkAllowance, formatReset, refusalFor } from './refusals';
import { StorageError, UploadCancelled, uploadFile, type UploadHandle } from './upload';
import { LIBRARY_KEY, UPLOAD_USAGE_KEY, useUploadUsage, type StorageUse } from './useLibrary';

type State =
  | { kind: 'idle' }
  | { kind: 'refused'; problem: FileProblem }
  | { kind: 'uploading'; file: File; percent: number }
  | { kind: 'failed'; file: File; error: unknown };

/** Announce progress to screen readers at these steps only, not on every event. */
const ANNOUNCE_EVERY = 25;

/**
 * Add a clip by uploading a file (`/library/add`, FR-CI-1, UI-4). The file is checked
 * here before any byte is sent, then goes straight to storage with progress and a
 * cancel button; the new clip then appears in the library as processing.
 */
export default function AddClipPage() {
  usePageTitle('Add a clip');
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const usage = useUploadUsage();
  const inputRef = useRef<HTMLInputElement>(null);
  const uploadRef = useRef<UploadHandle | null>(null);
  const [state, setState] = useState<State>({ kind: 'idle' });
  const [announcement, setAnnouncement] = useState('');
  const [dragging, setDragging] = useState(false);
  const fileNameId = useId();
  const hintId = useId();

  const uploading = state.kind === 'uploading';

  // Leaving the page cancels the upload; closing the tab asks first.
  useEffect(() => () => uploadRef.current?.cancel(), []);
  useEffect(() => {
    if (!uploading) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [uploading]);

  const start = (file: File) => {
    const problem = checkFile(file, usage.data?.max_file_bytes) ?? checkAllowance(file, usage.data);
    if (problem) {
      setState({ kind: 'refused', problem });
      return;
    }
    setState({ kind: 'uploading', file, percent: 0 });
    setAnnouncement(`Uploading ${file.name}.`);
    let announced = 0;
    const handle = uploadFile(file, ({ loaded, total }) => {
      const percent = total > 0 ? Math.min(100, Math.floor((loaded / total) * 100)) : 0;
      setState((current) => (current.kind === 'uploading' ? { ...current, percent } : current));
      const step = Math.floor(percent / ANNOUNCE_EVERY) * ANNOUNCE_EVERY;
      if (step > announced) {
        announced = step;
        setAnnouncement(
          step === 100 ? 'Upload finished. Adding the clip to your library.' : `Upload ${step}%`,
        );
      }
    });
    uploadRef.current = handle;
    handle.done.then(
      () => {
        uploadRef.current = null;
        void queryClient.invalidateQueries({ queryKey: LIBRARY_KEY });
        void queryClient.invalidateQueries({ queryKey: UPLOAD_USAGE_KEY });
        void navigate('/library');
      },
      (error: unknown) => {
        uploadRef.current = null;
        if (error instanceof UploadCancelled) {
          setState({ kind: 'idle' });
          setAnnouncement('Upload cancelled.');
          return;
        }
        // Storage use and today's allowance may have changed under a refusal.
        void queryClient.invalidateQueries({ queryKey: UPLOAD_USAGE_KEY });
        const refused = refusalFor(error);
        if (refused) {
          setState({ kind: 'refused', problem: refused });
          return;
        }
        setState({ kind: 'failed', file, error });
      },
    );
  };

  const cancel = () => uploadRef.current?.cancel();

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files[0];
    if (file && !uploading) start(file);
  };

  return (
    <main className="mx-auto flex w-full max-w-[50rem] flex-col gap-6 px-4 pt-4 pb-8 md:px-6 md:pt-8 md:pb-12">
      <Link
        to="/library"
        className="inline-flex min-h-11 items-center gap-1 self-start font-bold no-underline"
      >
        <BackIcon />
        Library
      </Link>
      <h1 className="font-display text-title-compact md:text-title">Add a clip</h1>

      <div
        onDragOver={(event) => {
          event.preventDefault();
          if (!uploading) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={`flex flex-col items-center gap-3 rounded-md border-2 border-dashed px-4 py-6 text-center md:py-12 ${
          dragging ? 'border-accent bg-accent-soft' : 'border-line-strong bg-surface-raised'
        }`}
      >
        <b className="hidden md:block">
          {dragging ? 'Drop to upload' : 'Drag an audio or video file here'}
        </b>
        <span className="hidden text-ink-muted md:block">or</span>
        <input
          ref={inputRef}
          type="file"
          aria-label="Choose a file"
          // The visible button below opens this picker; screen readers meet that one only.
          aria-hidden="true"
          accept={ACCEPT_ATTRIBUTE}
          className="sr-only"
          aria-describedby={hintId}
          disabled={uploading}
          tabIndex={-1}
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = '';
            if (file) start(file);
          }}
        />
        <button
          type="button"
          className={buttonClass('primary')}
          disabled={uploading}
          aria-describedby={hintId}
          onClick={() => inputRef.current?.click()}
        >
          Choose a file
        </button>
        <span id={hintId} className="text-body-s text-ink-muted">
          {ACCEPTED_NAMES}, up to {formatSize(usage.data?.max_file_bytes ?? 500 * 1024 * 1024)}
        </span>
      </div>

      {usage.data && (
        <div className="flex flex-col gap-1 text-body-s">
          <p>
            <b>{formatSize(usage.data.used_bytes)}</b> of {formatSize(usage.data.quota_bytes)} used
            by your uploads
          </p>
          {usage.data.daily_audio && <DailyAllowance daily={usage.data.daily_audio} />}
        </div>
      )}

      <div aria-live="polite" className="sr-only">
        {announcement}
      </div>

      {state.kind === 'uploading' && (
        <section
          aria-labelledby={fileNameId}
          aria-busy="true"
          className="flex flex-col gap-3 rounded-md border border-line bg-surface-raised p-4"
        >
          <div className="flex items-start justify-between gap-3">
            <div className="flex min-w-0 flex-col">
              <b id={fileNameId} className="break-words">
                {state.file.name}
              </b>
              <span className="font-mono text-body-s text-ink-muted">
                {formatSize(state.file.size)}
              </span>
            </div>
            <span className="font-mono font-bold">{state.percent}%</span>
          </div>
          <div
            role="progressbar"
            aria-labelledby={fileNameId}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={state.percent}
            className="h-2 overflow-hidden rounded-full bg-surface-sunken"
          >
            <div className="h-full bg-accent" style={{ width: `${state.percent}%` }} />
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="text-body-s text-ink-muted">
              {state.percent < 100
                ? 'Keep this tab open until the upload ends.'
                : 'Adding the clip to your library…'}
            </span>
            {state.percent < 100 && (
              <button type="button" className={buttonClass('secondary')} onClick={cancel}>
                Cancel upload
              </button>
            )}
          </div>
        </section>
      )}

      {state.kind === 'refused' && <RefusedFile problem={state.problem} />}
      {state.kind === 'failed' && (
        <UploadFailed error={state.error} onRetry={() => start(state.file)} />
      )}

      <p className="text-body-s text-ink-muted">
        Your files are private to your account. You can delete them any time.
      </p>
    </main>
  );
}

/** Today's new audio (D16, #41): how much is used, and when the count starts again. */
function DailyAllowance({ daily }: { daily: NonNullable<StorageUse['daily_audio']> }) {
  const used = Math.min(daily.limit_seconds, daily.used_seconds);
  return (
    <>
      <p>
        <b>{Math.floor(used / 60)}</b> of {Math.floor(daily.limit_seconds / 60)} minutes of new
        audio added today; the count starts again {formatReset(daily.resets_at)}.
      </p>
      <p className="text-ink-muted">
        A clip counts with at most 15 minutes, however long it is. Two of your clips are prepared at
        a time; the others wait in your queue.
      </p>
    </>
  );
}

function RefusedFile({ problem }: { problem: FileProblem }) {
  return (
    <div
      role="alert"
      className="grid grid-cols-[1.5rem_minmax(0,1fr)] gap-3 rounded-md border-2 border-danger bg-surface-raised p-4"
    >
      <span className="pt-0.5 text-danger">
        <AlertIcon className="size-6" />
      </span>
      <div className="flex flex-col gap-1">
        <h2 className="font-display text-heading break-words">{problem.title}</h2>
        <p>{problem.detail}</p>
      </div>
    </div>
  );
}

function UploadFailed({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  if (error instanceof StorageError) {
    return (
      <RefusedFile
        problem={{
          title: 'The upload did not go through',
          detail: 'Storage did not accept the file. Choose the file again to try once more.',
        }}
      />
    );
  }
  return <ErrorPanel error={error} onRetry={onRetry} />;
}
