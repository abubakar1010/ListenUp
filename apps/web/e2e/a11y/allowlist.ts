/*
 * Known serious or critical axe violations the scan accepts for now (#98). Only a
 * screen another open story owns may have an entry (a scan state with `owner`), and
 * the entry links that story's issue. An entry that no longer matches fails the scan,
 * so the list only shrinks.
 */

export interface AllowedViolation {
  /** The axe rule id, for example `color-contrast`. */
  rule: string;
  /** The scan state's name in `states.ts`. */
  state: string;
  /** Why it stays, and what will fix it. */
  reason: string;
  /** The GitHub issue that owns the fix. */
  issue: string;
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
    if (!owners.has(entry.state)) problems.push(`${label} names no scan state`);
    else if (owners.get(entry.state) !== entry.issue)
      problems.push(`${label} is not on a screen owned by ${entry.issue}`);
    return problems;
  });
}
