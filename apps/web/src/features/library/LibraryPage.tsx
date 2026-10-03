import { usePageTitle } from '../../app/usePageTitle';

const STEPS = [
  {
    label: '1 · Listen first',
    name: 'Blind or Dictation',
    text: "Hear the clip before you see any text, so you find what you really can't catch.",
  },
  {
    label: '2 · Find the gaps',
    name: 'Transcript',
    text: "Read along and mark every place where the sound didn't match the words.",
  },
  {
    label: '3 · Train them',
    name: 'Card and Shadow',
    text: 'Keep two sounds, then speak with the speaker three times.',
  },
];

/** The learner's library (`/library`). Clips, marks and cards arrive with their stories. */
export default function LibraryPage() {
  usePageTitle('Library');

  return (
    <main className="mx-auto flex w-full max-w-content flex-col gap-6 px-4 pt-4 pb-8 md:gap-8 md:px-6 md:pt-8 md:pb-12 xl:px-8">
      <h1 className="font-display text-title-compact md:text-title">Library</h1>
      <section
        aria-labelledby="library-empty"
        className="grid justify-items-center gap-3 rounded-md border-2 border-dashed border-line-strong bg-surface-raised px-4 py-8 text-center md:py-16"
      >
        <h2 id="library-empty" className="font-display text-heading-compact md:text-heading">
          No clips yet
        </h2>
        <p className="max-w-[68ch]">
          Your clips will show here. Two to three minutes of a talk, podcast or show is enough for
          one plan.
        </p>
      </section>
      <section aria-labelledby="library-how" className="flex flex-col gap-4">
        <h2 id="library-how" className="font-display text-heading-compact md:text-heading">
          How a plan works
        </h2>
        <ol className="grid gap-4 md:grid-cols-3">
          {STEPS.map((step) => (
            <li
              key={step.label}
              className="flex flex-col gap-1 rounded-md border border-line bg-surface-raised p-4"
            >
              <span className="text-label text-ink-muted uppercase">{step.label}</span>
              <b>{step.name}</b>
              <span className="text-body-s text-ink-muted">{step.text}</span>
            </li>
          ))}
        </ol>
      </section>
    </main>
  );
}
