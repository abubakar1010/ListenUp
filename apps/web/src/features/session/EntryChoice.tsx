import { STEP_DESCRIPTIONS, STEP_NAMES } from './plan';

type EntryStep = 'blind' | 'dictation';

export interface EntryChoiceProps {
  blind: boolean;
  dictation: boolean;
  onChange: (step: EntryStep, checked: boolean) => void;
  /** Steps that cannot change, with the reason shown beside them ("done, kept"). */
  fixed?: Partial<Record<EntryStep, string>>;
  /** Shown under the boxes and linked to them, for example "Tick Blind, Dictation or both." */
  error?: string;
  idPrefix: string;
}

const BADGES: Record<EntryStep, string | null> = {
  blind: 'Recommended to start',
  dictation: null,
};

/**
 * Blind, Dictation or both (FR-PL-1), each with its one-line rule (UI-2). Two
 * checkboxes; with both, Blind always comes first (OQ-1), so there is no order control.
 */
export function EntryChoice({
  blind,
  dictation,
  onChange,
  fixed = {},
  error,
  idPrefix,
}: EntryChoiceProps) {
  const errorId = `${idPrefix}-entry-error`;
  const values: Record<EntryStep, boolean> = { blind, dictation };
  return (
    <fieldset
      className="flex flex-col gap-3"
      aria-describedby={error ? errorId : undefined}
      aria-invalid={error ? true : undefined}
    >
      <legend className="sr-only">Entry exercises</legend>
      {(['blind', 'dictation'] as const).map((step) => {
        const reason = fixed[step];
        const id = `${idPrefix}-${step}`;
        return (
          <label
            key={step}
            htmlFor={id}
            className={`flex cursor-pointer gap-3 rounded-md border-2 p-4 ${
              values[step] ? 'border-accent bg-accent-soft' : 'border-line bg-surface-raised'
            } ${reason ? 'cursor-not-allowed' : ''}`}
          >
            <input
              id={id}
              type="checkbox"
              className="mt-1 size-5 flex-none accent-accent"
              checked={values[step]}
              disabled={reason !== undefined}
              aria-describedby={`${id}-description`}
              onChange={(event) => onChange(step, event.target.checked)}
            />
            <span className="flex min-w-0 flex-col gap-1">
              <span className="flex flex-wrap items-center gap-2">
                <b className="font-display text-heading-compact">{STEP_NAMES[step]}</b>
                {BADGES[step] && !reason && (
                  <span className="rounded-full border border-line px-2 text-body-s">
                    {BADGES[step]}
                  </span>
                )}
                {reason && <span className="text-body-s text-ink-muted">· {reason}</span>}
              </span>
              <span id={`${id}-description`}>{STEP_DESCRIPTIONS[step]}</span>
            </span>
          </label>
        );
      })}
      {error && (
        <p id={errorId} className="font-bold text-danger">
          {error}
        </p>
      )}
    </fieldset>
  );
}
