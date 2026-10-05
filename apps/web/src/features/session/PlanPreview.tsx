import { pathFor, STEP_NAMES, type Entry } from './plan';

/** The steps a choice of entry gives, announced politely as it changes (FR-PL-2). */
export function PlanPreview({ entry, lead = 'Your plan' }: { entry: Entry | null; lead?: string }) {
  const steps = entry ? pathFor(entry) : [];
  return (
    <div aria-live="polite" className="flex flex-col gap-2">
      {entry ? (
        <>
          <p className="font-bold">
            {lead}: {steps.length} steps
          </p>
          <ol className="flex list-decimal flex-col gap-1 pl-6">
            {steps.map((step) => (
              <li key={step}>{STEP_NAMES[step]}</li>
            ))}
          </ol>
        </>
      ) : (
        <p className="font-bold">{lead}: tick Blind, Dictation or both.</p>
      )}
    </div>
  );
}
