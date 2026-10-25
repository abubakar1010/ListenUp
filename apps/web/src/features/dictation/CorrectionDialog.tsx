import { useId, useRef, useState } from 'react';

import { ConfirmDialog } from '../../components/ConfirmDialog';
import { ErrorPanel } from '../../components/ErrorPanel';
import { type DiffItem, useDisputeWord } from './api';

export function CorrectionDialog({
  sessionId,
  attemptId,
  item,
  onClose,
}: {
  sessionId: string;
  attemptId: string;
  item: DiffItem;
  onClose: () => void;
}) {
  const [text, setText] = useState(item.word);
  const inputId = useId();
  const key = useRef<string | null>(null);
  const save = useDisputeWord(sessionId, attemptId, onClose);
  function submit() {
    if (save.isPending || item.index === null) return;
    key.current ??= crypto.randomUUID();
    save.mutate({ wordIndex: item.index, text, key: key.current });
  }
  return (
    <ConfirmDialog
      title={`Correct reference word ${item.word || '(removed word)'}`}
      confirmLabel="Save correction"
      cancelLabel="Cancel"
      onConfirm={submit}
      onCancel={onClose}
      busy={save.isPending}
      footer={save.isError ? <ErrorPanel error={save.error} onRetry={submit} /> : undefined}
    >
      <span className="block">
        This changes your reference and accuracy. Other learners keep the original text. Existing
        marks and notes stay saved.
      </span>
      <label htmlFor={inputId} className="mt-3 block">
        Corrected text
      </label>
      <input
        id={inputId}
        value={text}
        maxLength={60}
        disabled={save.isPending}
        className="w-full rounded-md border border-line bg-surface px-3 py-2 text-ink"
        onChange={(event) => {
          setText(event.target.value);
          key.current = null;
          save.reset();
        }}
      />
      <span className="block text-body-s text-ink-muted">
        Up to 60 characters. Leave empty to remove this word.
      </span>
    </ConfirmDialog>
  );
}
