import { AlertIcon, CheckIcon } from '../../components/icons';
import type { AutosaveStatus } from './autosave';
import { saveStatusText } from './statusText';

/** The "saved" indicator: a tick when the server has everything, a warning when not. */
export function SaveStatus<T>({
  status,
  noun,
  className = '',
}: {
  status: AutosaveStatus<T>;
  noun?: string;
  className?: string;
}) {
  const problem = ['offline', 'retrying', 'conflict', 'failed'].includes(status.kind);
  return (
    <span
      data-save-status={status.kind}
      className={`inline-flex items-center gap-1 ${problem ? 'text-warning' : ''} ${className}`.trim()}
    >
      {status.kind === 'saved' && <CheckIcon className="size-4 text-success" />}
      {problem && <AlertIcon className="size-4" />}
      {saveStatusText(status, noun)}
    </span>
  );
}
