import {
  formatClock,
  formatLength,
  MAX_PASSAGE_MS,
  MIN_PASSAGE_MS,
  spokenLength,
  wholeFits,
  type PassageValue,
} from './time';

interface PassagePickerProps {
  durationMs: number | null;
  value: PassageValue;
  onChange: (value: PassageValue) => void;
  errors: { start?: string; end?: string };
  /** Length of the chosen part when it is valid, for the "2:30 long" badge. */
  lengthMs: number | null;
}

/**
 * The part of the clip to practise, 30 s to 15 min (C2). Until the waveform picker
 * (#42) lands, the part is typed as start and end times in mm:ss.
 */
export function PassagePicker({
  durationMs,
  value,
  onChange,
  errors,
  lengthMs,
}: PassagePickerProps) {
  const wholeAllowed = durationMs !== null && wholeFits(durationMs);
  return (
    <div className="flex flex-col gap-4">
      <fieldset className="grid gap-3 sm:grid-cols-2">
        <legend className="sr-only">Passage</legend>
        <label
          className={`flex gap-3 rounded-md border-2 p-4 ${
            value.mode === 'whole'
              ? 'border-accent bg-accent-soft'
              : 'border-line bg-surface-raised'
          } ${wholeAllowed ? 'cursor-pointer' : 'cursor-not-allowed bg-surface-sunken'}`}
        >
          <input
            type="radio"
            name="passage-mode"
            className="mt-1 size-5 flex-none accent-accent"
            checked={value.mode === 'whole'}
            disabled={!wholeAllowed}
            aria-describedby="passage-whole-note"
            onChange={() =>
              durationMs !== null &&
              onChange({ mode: 'whole', start: formatClock(0), end: formatClock(durationMs) })
            }
          />
          <span className="flex flex-col gap-1">
            <b>
              Whole clip
              {durationMs !== null && (
                <>
                  {' · '}
                  <span className="font-mono">{formatClock(durationMs)}</span>
                </>
              )}
            </b>
            <span id="passage-whole-note" className="text-body-s text-ink-muted">
              {wholeNote(durationMs)}
            </span>
          </span>
        </label>
        <label
          className={`flex cursor-pointer gap-3 rounded-md border-2 p-4 ${
            value.mode === 'part' ? 'border-accent bg-accent-soft' : 'border-line bg-surface-raised'
          }`}
        >
          <input
            type="radio"
            name="passage-mode"
            className="mt-1 size-5 flex-none accent-accent"
            checked={value.mode === 'part'}
            onChange={() => onChange({ ...value, mode: 'part' })}
          />
          <span className="flex flex-col gap-1">
            <b>A part of it</b>
            <span className="text-body-s text-ink-muted">Recommended: 2 to 3 minutes.</span>
          </span>
        </label>
      </fieldset>

      {value.mode === 'part' && (
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-start gap-3">
            <TimeField
              id="passage-start"
              label="Start"
              value={value.start}
              error={errors.start}
              onChange={(start) => onChange({ ...value, start })}
            />
            <TimeField
              id="passage-end"
              label="End"
              value={value.end}
              error={errors.end}
              onChange={(end) => onChange({ ...value, end })}
            />
          </div>
          <p className="text-body-s text-ink-muted">
            Minutes and seconds, for example 02:10. Any part from 30 seconds to 15 minutes.
          </p>
        </div>
      )}
      {lengthMs !== null && (
        <p className="self-start rounded-full border border-line px-3 text-body-s">
          <span aria-hidden="true">
            <span className="font-mono">{formatLength(lengthMs)}</span> long
          </span>
          <span className="sr-only">{spokenLength(lengthMs)} selected</span>
        </p>
      )}
    </div>
  );
}

function wholeNote(durationMs: number | null): string {
  if (durationMs === null) return 'The clip’s length is not known yet.';
  if (durationMs > MAX_PASSAGE_MS)
    return 'Too long to use whole. Choose a part of 15 minutes or less.';
  if (durationMs < MIN_PASSAGE_MS) return 'Too short: a plan needs at least 30 seconds.';
  if (durationMs > 5 * 60_000) return 'Within the 15-minute limit. Long for Dictation.';
  return 'Within the 15-minute limit.';
}

function TimeField({
  id,
  label,
  value,
  error,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  error?: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="flex w-full max-w-xs flex-col gap-1 sm:w-56">
      <label htmlFor={id} className="font-bold">
        {label}
      </label>
      <input
        id={id}
        className="min-h-11 rounded-md border border-line-strong bg-surface-raised px-3 font-mono aria-invalid:border-danger"
        inputMode="numeric"
        autoComplete="off"
        value={value}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        onChange={(event) => onChange(event.target.value)}
      />
      {error && (
        <p id={`${id}-error`} className="text-body-s font-bold text-danger">
          {error}
        </p>
      )}
    </div>
  );
}
