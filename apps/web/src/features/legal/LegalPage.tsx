import { PageLoading } from '../../app/PageLoading';
import { usePageTitle } from '../../app/usePageTitle';
import { DOCUMENTS, type ConsentKind, useConsentVersions } from '../../auth/consentApi';
import { errorMessage } from '../../auth/errorMessage';
import { LegalText } from './LegalText';
import { TEXTS } from './texts';

/**
 * The Terms of Service, Privacy Policy and voice recording consent (#103). Shows the
 * text of the version learners accept now (`GET /auth/consent-versions`, ADR 0048), so
 * the page and the recorded consent always name the same text (ADR 0051).
 */
export default function LegalPage({ document }: { document: ConsentKind }) {
  const { name } = DOCUMENTS[document];
  usePageTitle(name);
  const versions = useConsentVersions();
  const version = versions.data?.[document];
  // Own keys only: a label such as `constructor` must not find an inherited property.
  const texts = TEXTS[document];
  const text = version !== undefined && Object.hasOwn(texts, version) ? texts[version] : undefined;

  return (
    <main className="mx-auto flex max-w-reading flex-col gap-4 p-6">
      {versions.isPending ? (
        <PageLoading />
      ) : text !== undefined ? (
        <LegalText source={text} />
      ) : (
        <>
          <h1 className="font-display text-title-compact">{name}</h1>
          <p role="alert" className="text-danger">
            {versions.isError
              ? errorMessage(versions.error)
              : `The text of version ${version} is not available here.`}
          </p>
        </>
      )}
    </main>
  );
}
