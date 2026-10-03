import type { Session } from './api';
import { pathFor, type Entry, type Step } from './plan';

/** A session as the API returns it, for tests: `done` steps finished, the next one open. */
export function sessionFixture({
  id = 'session-1',
  entry = 'blind' as Entry,
  done = 0,
  skipped = [] as Step[],
  ...overrides
}: Partial<Session> & { done?: number; skipped?: Step[] } = {}): Session {
  const path = pathFor(entry);
  const steps = path.map((step, index) => ({
    step,
    position: index + 1,
    status:
      index < done
        ? skipped.includes(step)
          ? ('skipped' as const)
          : ('done' as const)
        : index === done
          ? ('open' as const)
          : ('locked' as const),
  }));
  const complete = done >= path.length;
  const open = complete ? null : path[done];
  return {
    id,
    content_id: 'clip-1',
    content_title: 'Why cities plant street trees',
    passage: { start_ms: 130_000, end_ms: 280_000 },
    entry,
    status: complete ? 'completed' : 'active',
    version: done,
    steps,
    step_count: path.length,
    open_step: open,
    open_position: complete ? null : done + 1,
    entry_locked: done >= path.indexOf('transcript'),
    entry_locked_at: null,
    completed_at: complete ? '2026-10-03T10:00:00Z' : null,
    created_at: '2026-10-03T09:00:00Z',
    updated_at: '2026-10-03T09:30:00Z',
    ...overrides,
  };
}
