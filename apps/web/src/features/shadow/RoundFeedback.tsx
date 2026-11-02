import { useRoundGrade, type RoundGrade } from './api';

type WordLabel = RoundGrade['word_labels'][number];
type Reason = WordLabel['reasons'][number];

const MEASURES: [keyof RoundGrade['measures'], string][] = [
  ['timing', 'Rhythm and timing'],
  ['pronunciation', 'Pronunciation'],
  ['articulation', 'Articulation'],
  ['fluency', 'Fluency'],
  ['fillers', 'Filler words'],
  ['completeness', 'Completeness'],
];
const POSITIONS: Record<Reason['position'], string> = {
  initial: 'start',
  medial: 'middle',
  final: 'ending',
};
const ISSUES: Record<Reason['issue'], string> = {
  dropped: 'dropped',
  merged: 'merged into a neighbouring sound',
  unclear: 'unclear',
  inaccurate: 'not quite right',
};

function reasonText(reason: Reason) {
  const linking = !reason.linking
    ? ''
    : reason.position === 'initial'
      ? ', where it links from the word before'
      : ', where it links to the next word';
  return `${POSITIONS[reason.position]} sound “${reason.sound}” ${ISSUES[reason.issue]}${linking}`;
}

function why(word: WordLabel) {
  if (word.label === 'missed') return 'missed';
  return word.reasons.length ? word.reasons.map(reasonText).join('; ') : 'needs work';
}

/**
 * Markers use a line style or a glyph plus words, one neutral hue, never red to green
 * (FR-SH-10, UX-01, UX-12, WCAG 1.4.1). Good words carry no mark.
 */
function Marked({ word }: { word: WordLabel }) {
  if (word.label === 'good') return <span data-label="good">{word.text}</span>;
  const missed = word.label === 'missed';
  return (
    <span data-label={word.label}>
      {missed && <span aria-hidden="true">○ </span>}
      <span
        className={
          missed
            ? 'text-ink-muted'
            : 'font-bold underline decoration-accent decoration-dotted decoration-2 underline-offset-4'
        }
      >
        {word.text}
      </span>
      <span className="sr-only"> ({missed ? 'missed' : 'needs work'})</span>
    </span>
  );
}

/**
 * One round's feedback. Under E2 the server always answers unavailable (ADR 0074, 0099);
 * a failed read is unavailable too, never a number.
 */
export function RoundFeedback({
  roundId,
  round,
  showMarkers,
  headingLevel = 4,
}: {
  roundId: string;
  round: number;
  /** False while a round is being shadowed: rounds 2 and 3 are spoken without text. */
  showMarkers: boolean;
  /** One below the round's own heading. */
  headingLevel?: 3 | 4;
}) {
  const Heading = headingLevel === 3 ? 'h3' : 'h4';
  const query = useRoundGrade(roundId);
  const grade = query.data?.status === 'scored' ? (query.data as RoundGrade) : null;
  if (!grade) return query.isPending ? null : <p>Feedback unavailable.</p>;
  const work = grade.word_labels.filter((word) => word.label !== 'good');
  return (
    <div className="flex min-w-0 flex-col gap-3 [overflow-wrap:anywhere]">
      <p className="font-bold">
        Round {round} score: {grade.overall} / 100
      </p>
      <ul aria-label={`Round ${round} measures`}>
        {MEASURES.map(([name, label]) => {
          const score = grade.measures[name].score;
          return (
            <li key={name}>
              {label}: {score === null ? 'not measured' : `${score} / 100`}
            </li>
          );
        })}
      </ul>
      <section
        aria-label={`Round ${round} accent guidance`}
        className="flex flex-col gap-1 rounded-md border border-dashed border-line p-3"
      >
        <Heading className="font-bold">Accent guidance</Heading>
        <p className="flex flex-wrap gap-2">
          <span className="rounded-sm border border-line px-2">Experimental</span>
          <span className="rounded-sm border border-line px-2">Not in your score</span>
        </p>
        <p>
          {grade.accent.score === null
            ? 'Not enough speech to compare with this speaker.'
            : `Compared with this speaker: ${grade.accent.score} / 100`}
        </p>
        <p>
          How close your vowels, stress and pitch were to this speaker. It is guidance, not a
          judgement of correct English.
        </p>
      </section>
      {showMarkers ? (
        <section aria-label={`Round ${round} word markers`} className="flex flex-col gap-2">
          <Heading className="font-bold">Word markers</Heading>
          <p>
            Words with no mark sounded good. A dotted underline means needs work; ○ means missed.
          </p>
          <p aria-label="Segment transcript with word markers">
            {grade.word_labels.map((word, i) => (
              <span key={word.index}>
                {i > 0 && ' '}
                <Marked word={word} />
              </span>
            ))}
          </p>
          {work.length > 0 && (
            <ul aria-label={`Round ${round} words to work on`}>
              {work.map((word) => (
                <li key={word.index}>
                  {word.text}: {why(word)}
                </li>
              ))}
            </ul>
          )}
        </section>
      ) : (
        <p>Word markers come back when the current round ends.</p>
      )}
    </div>
  );
}
