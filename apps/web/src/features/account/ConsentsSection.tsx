import { useId, useState } from 'react';

import { DOCUMENTS, useMyConsents, useWithdrawConsent, type Consents } from '../../auth/consentApi';
import { errorMessage } from '../../auth/errorMessage';
import { buttonClass } from '../../components/button';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { ErrorPanel } from '../../components/ErrorPanel';

type Record = Consents['consents'][number];

function formatDay(iso: string): string {
  return new Date(iso).toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  });
}

function label(record: Record): string {
  const name = `${DOCUMENTS[record.kind].name}, version ${record.version}`;
  if (record.withdrawn_at) return `${name} (withdrawn)`;
  return record.current ? name : `${name} (earlier version)`;
}

/**
 * "Agreements" (#104): the versions of the Terms of Service, Privacy Policy and voice
 * recording consent the learner accepted, and withdrawing voice consent (FR-SH-17).
 * Terms and privacy apply while the account exists; deleting it is the way out.
 */
export function ConsentsSection() {
  const headingId = useId();
  const consents = useMyConsents();
  const withdraw = useWithdrawConsent();
  const [asking, setAsking] = useState(false);

  const records = consents.data?.consents ?? [];
  const voice = records.filter((c) => c.kind === 'voice_recording');
  // Any version not yet withdrawn can be withdrawn; the server withdraws them all.
  const activeVoice = voice.find((c) => c.withdrawn_at === null);
  const withdrawnVoice = voice.find((c) => c.withdrawn_at !== null);

  return (
    <section
      aria-labelledby={headingId}
      className="flex flex-col gap-4 rounded-md border border-line bg-surface-raised p-4 md:p-6"
    >
      <h2 id={headingId} className="font-display text-heading-compact md:text-heading">
        Agreements
      </h2>
      {consents.isPending ? (
        <p role="status" className="text-ink-muted">
          Loading your agreements…
        </p>
      ) : consents.isError ? (
        <ErrorPanel error={consents.error} onRetry={() => void consents.refetch()} />
      ) : (
        <>
          <ul className="flex flex-col gap-2">
            {records.map((record) => (
              <li key={`${record.kind}:${record.version}`} className="flex flex-col">
                <span>{label(record)}</span>
                <span className="text-body-s text-ink-muted">
                  Accepted {formatDay(record.granted_at)}
                </span>
              </li>
            ))}
          </ul>
          {activeVoice ? (
            <>
              <p>
                {activeVoice.current
                  ? 'You agreed to voice recording for Shadow practice. If you withdraw, your next Shadow round asks again before recording.'
                  : 'You agreed to an earlier version of voice recording consent. ListenUp asks you to agree to the current version before your next Shadow round, and you can withdraw the earlier one now.'}
              </p>
              <div>
                <button
                  type="button"
                  className={buttonClass('secondary')}
                  onClick={() => {
                    withdraw.reset();
                    setAsking(true);
                  }}
                >
                  Withdraw voice recording consent
                </button>
              </div>
            </>
          ) : withdrawnVoice?.withdrawn_at ? (
            <p role="status">
              You withdrew voice recording consent on {formatDay(withdrawnVoice.withdrawn_at)}.
              ListenUp asks again before your next Shadow round.
            </p>
          ) : (
            <p>
              You have not agreed to voice recording. ListenUp asks before your first Shadow round.
            </p>
          )}
        </>
      )}
      {asking && (
        <ConfirmDialog
          title="Withdraw voice recording consent?"
          confirmLabel="Withdraw consent"
          cancelLabel="Keep my consent"
          busy={withdraw.isPending}
          busyLabel="Withdrawing…"
          onConfirm={() =>
            withdraw.mutate('voice_recording', { onSuccess: () => setAsking(false) })
          }
          onCancel={() => setAsking(false)}
          footer={
            withdraw.isError ? (
              <p role="alert" className="text-danger">
                {errorMessage(withdraw.error)}
              </p>
            ) : undefined
          }
        >
          <p>New Shadow rounds will not record until you agree again.</p>
        </ConfirmDialog>
      )}
    </section>
  );
}
