import { usePageTitle } from '../../app/usePageTitle';
import { DOCUMENTS } from '../../auth/consentApi';

/**
 * The Terms of Service and Privacy Policy (#104). PLACEHOLDER: the policy text is
 * written in #103; until then these pages say so, and the versions learners accept
 * are the placeholder labels in LISTENUP_TERMS_VERSION and LISTENUP_PRIVACY_VERSION
 * (ADR 0048).
 */
export default function LegalPage({ document }: { document: 'terms' | 'privacy' }) {
  const { name } = DOCUMENTS[document];
  usePageTitle(name);
  return (
    <main className="mx-auto flex max-w-reading flex-col gap-4 p-6">
      <h1 className="font-display text-title-compact">{name}</h1>
      <p className="rounded-md border border-line bg-surface-raised p-4 font-bold">
        Placeholder: the final text of this document is not written yet. It will replace this page
        before ListenUp opens to the public.
      </p>
      {document === 'privacy' && (
        <p>
          In short, as the product is designed: your recordings, media and texts are used only for
          your own practice, are never sold or shared, and are never used to train AI models.
        </p>
      )}
    </main>
  );
}
