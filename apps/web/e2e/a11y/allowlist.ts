/*
 * Known serious or critical axe violations the scan accepts for now (#98). Only a
 * screen owned by #70, #73 or #79 may have an entry (a scan state with that `owner`),
 * and the entry links that story's issue. An entry that no longer matches fails the
 * scan, so the list only shrinks.
 */

export const ISSUE = 'https://github.com/abubakar1010/ListenUp/issues';
/** The open stories whose screens may carry an exception. */
export const OWNERS = new Set([`${ISSUE}/70`, `${ISSUE}/73`, `${ISSUE}/79`]);
/** The Playwright projects that run the scan (`playwright.config.ts`). */
export const PROJECTS = ['a11y-desktop', 'a11y-360', 'a11y-dark'];

export interface AllowedViolation {
  /** The axe rule id, for example `color-contrast`. */
  rule: string;
  /** The scan state's name in `states.ts`. */
  state: string;
  /** Why it stays, and what will fix it. */
  reason: string;
  /** The GitHub issue that owns the fix. */
  issue: string;
  /** Only in these projects, for a violation that one width or theme shows; all by default. */
  projects?: string[];
}

export const ALLOWED: AllowedViolation[] = [];

const ISSUE_URL = /^https:\/\/github\.com\/abubakar1010\/ListenUp\/issues\/\d+$/;

/** Problems with the entries themselves; the spec fails on any. */
export function allowlistProblems(
  entries: AllowedViolation[],
  owners: Map<string, string | undefined>,
): string[] {
  return entries.flatMap((entry) => {
    const label = `${entry.rule} on "${entry.state}"`;
    const problems: string[] = [];
    if (!entry.reason.trim()) problems.push(`${label} has no reason`);
    if (!ISSUE_URL.test(entry.issue)) problems.push(`${label} does not link a GitHub issue`);
    else if (!OWNERS.has(entry.issue))
      problems.push(`${label} links ${entry.issue}, which may not hold exceptions`);
    if (!owners.has(entry.state)) problems.push(`${label} names no scan state`);
    else if (owners.get(entry.state) !== entry.issue)
      problems.push(`${label} is not on a screen owned by ${entry.issue}`);
    if (entry.projects?.length === 0) problems.push(`${label} lists no project`);
    for (const project of entry.projects ?? [])
      if (!PROJECTS.includes(project)) problems.push(`${label} names unknown project ${project}`);
    return problems;
  });
}

/** Scan states marked as owned by a story that may not hold exceptions. */
export function ownerProblems(states: { name: string; owner?: string }[]): string[] {
  return states
    .filter((state) => state.owner !== undefined && !OWNERS.has(state.owner))
    .map((state) => `"${state.name}" is owned by ${state.owner}, which may not hold exceptions`);
}

/** The entries that apply to one scan state in one project. */
export function allowedFor(entries: AllowedViolation[], state: string, project: string) {
  return entries.filter(
    (entry) => entry.state === state && (entry.projects?.includes(project) ?? true),
  );
}
