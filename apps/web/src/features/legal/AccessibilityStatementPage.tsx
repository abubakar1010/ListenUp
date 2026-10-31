import statement from '../../../../../docs/legal/accessibility-statement.md?raw';
import { usePageTitle } from '../../app/usePageTitle';
import { LegalText } from './LegalText';

/**
 * The accessibility statement (#98, NFR-USE-2). Its text lives in
 * docs/legal/accessibility-statement.md, so it is reviewed like the legal drafts.
 */
export default function AccessibilityStatementPage() {
  usePageTitle('Accessibility statement');
  return (
    <main className="mx-auto flex max-w-reading flex-col gap-4 p-6">
      <LegalText source={statement} />
    </main>
  );
}
