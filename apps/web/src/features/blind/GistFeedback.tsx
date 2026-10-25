import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import type { components } from '../../api/schema';
import { GIST_GRADE_KEY, useBlindStep } from './api';

type Grade = components['schemas']['GistFeedback'];
const LEVELS = { needs_work: 'Needs work', fair: 'Fair', good: 'Good', excellent: 'Excellent' };
const PARTS: Record<string, string> = {
  main_idea: 'Main idea',
  key_details: 'Key details',
  accuracy: 'Accuracy',
};

/** Context is part of the cache key: a summary from Blind cannot mask Transcript details. */
export function GistFeedback({
  attemptId,
  context,
}: {
  attemptId: string;
  context: 'blind' | 'transcript';
}) {
  const query = useQuery({
    queryKey: [...GIST_GRADE_KEY, attemptId, context],
    queryFn: () => api<Grade>(`/gists/${encodeURIComponent(attemptId)}/grade`),
    refetchInterval: (state) => (state.state.data?.status === 'ready' ? false : 5000),
  });
  const grade = query.data;
  const ready = grade?.status === 'ready';
  return (
    <section
      aria-label="Gist feedback"
      aria-busy={!ready}
      className="flex min-w-0 flex-col gap-3 rounded-md border border-line bg-surface-raised p-4 [overflow-wrap:anywhere]"
    >
      <h2 className="font-display text-heading">Your gist feedback</h2>
      <p aria-live={context === 'blind' ? 'polite' : 'off'}>
        {ready ? 'Your gist feedback is ready.' : 'Preparing your gist feedback…'}
      </p>
      {grade?.gist && (
        <div>
          <h3 className="font-bold">Your gist</h3>
          <p className="whitespace-pre-wrap">{grade.gist}</p>
        </div>
      )}
      {ready && (
        <>
          <p className="font-bold">{grade.overall} / 100</p>
          {grade.level && <p>{LEVELS[grade.level]}</p>}
          <ul aria-label="Rubric part scores">
            {Object.entries(grade.dimension_scores ?? {}).map(([name, score]) => (
              <li key={name}>
                {PARTS[name] ?? name}: {score} / 100
              </li>
            ))}
          </ul>
          <p>
            You captured {grade.captured_count} of {grade.total_count} key points
          </p>
          {grade.feedback && <p>{grade.feedback}</p>}
          {grade.key_points && (
            <ul aria-label="Key points" className="flex flex-col gap-2">
              {grade.key_points.map((point, index) => (
                <li key={index}>
                  <span aria-hidden="true">{point.captured ? '✓' : '○'} </span>
                  {point.captured ? 'Captured' : 'Missed'}: {point.text}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}

export function TranscriptGistPanel({ sessionId }: { sessionId: string }) {
  const blind = useBlindStep(sessionId);
  const attempt = blind.data?.attempt;
  return attempt?.status === 'submitted' ? (
    <GistFeedback attemptId={attempt.id} context="transcript" />
  ) : (
    <section aria-label="Gist feedback" aria-busy="true">
      <h2 className="font-display text-heading">Your gist feedback</h2>
      <p>Preparing your gist feedback…</p>
    </section>
  );
}
