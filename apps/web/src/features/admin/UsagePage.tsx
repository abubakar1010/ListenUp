import { Link } from 'react-router';

import NotFoundPage from '../../app/NotFoundPage';
import { usePageTitle } from '../../app/usePageTitle';
import { buttonClass } from '../../components/button';
import { ErrorPanel } from '../../components/ErrorPanel';
import { isNotAdmin, useUsageOverview, type UsageOverview } from './adminApi';
import { BusyButton } from '../../components/BusyButton';

const CELL = 'border-b border-line px-3 py-2 text-left align-top tabular-nums';
const number = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 });

function allowance(used: number, limits: Record<string, number> | null, dimension: string) {
  if (limits === null) return `Unknown allowance; ${number.format(used)} used`;
  const limit = limits[dimension];
  if (limit === undefined) return `Uncapped; ${number.format(used)} used`;
  if (limit === 0) return `No allowance (0); ${number.format(used)} used`;
  return `${number.format(used)} / ${number.format(limit)} (${number.format((used / limit) * 100)}%)`;
}

function ProviderReport({ provider }: { provider: UsageOverview['providers'][number] }) {
  return (
    <section className="min-w-0 rounded-md border border-line bg-surface-raised p-4 md:p-6">
      <h2 className="font-display text-heading-compact">{provider.provider}</h2>
      <div
        className="mt-4 overflow-x-auto"
        role="region"
        aria-label={`${provider.provider} quotas`}
        tabIndex={0}
      >
        <table className="w-full border-collapse text-body-s">
          <caption className="text-left font-bold">{provider.provider} current free quota</caption>
          <thead>
            <tr>
              {['Period (UTC)', 'Calls', 'Tokens', 'Audio seconds'].map((label) => (
                <th scope="col" className={CELL} key={label}>
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {provider.quotas.map((quota) => (
              <tr key={quota.period}>
                <th scope="row" className={CELL}>
                  {quota.period === 'day' ? 'Today' : 'This calendar month'}
                </th>
                <td className={CELL}>{allowance(quota.calls, quota.limits, 'calls')}</td>
                <td className={CELL}>{allowance(quota.tokens, quota.limits, 'tokens')}</td>
                <td className={CELL}>
                  {allowance(quota.audio_seconds, quota.limits, 'audio_seconds')}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div
        className="mt-6 overflow-x-auto"
        role="region"
        aria-label={`${provider.provider} history`}
        tabIndex={0}
      >
        <table className="w-full border-collapse text-body-s">
          <caption className="text-left font-bold">{provider.provider} daily usage (UTC)</caption>
          <thead>
            <tr>
              {[
                'Date',
                'Calls',
                'Input tokens',
                'Output tokens',
                'Audio seconds',
                'Estimated cost (USD)',
                'Estimated calls',
              ].map((label) => (
                <th scope="col" className={CELL} key={label}>
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {provider.days.map((day) => (
              <tr key={day.date}>
                <th scope="row" className={`${CELL} whitespace-nowrap`}>
                  {day.date}
                </th>
                <td className={CELL}>{number.format(day.calls)}</td>
                <td className={CELL}>{number.format(day.input_tokens)}</td>
                <td className={CELL}>{number.format(day.output_tokens)}</td>
                <td className={CELL}>{number.format(day.audio_seconds)}</td>
                <td className={CELL}>${day.estimated_cost_usd.toFixed(4)}</td>
                <td className={CELL}>{number.format(day.estimated_calls)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default function UsagePage() {
  usePageTitle('AI usage');
  const report = useUsageOverview();
  if (report.isError && isNotAdmin(report.error)) return <NotFoundPage />;
  return (
    <main className="mx-auto flex w-full min-w-0 max-w-content flex-col gap-6 px-4 py-8 md:px-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-display text-title-compact md:text-title">AI usage</h1>
        <BusyButton
          className={buttonClass('secondary')}
          busy={report.isFetching}
          onClick={() => void report.refetch()}
        >
          {report.isFetching ? 'Refreshing…' : 'Refresh'}
        </BusyButton>
      </div>
      {report.isPending ? (
        <p role="status">Loading usage…</p>
      ) : report.isError ? (
        <ErrorPanel error={report.error} onRetry={() => void report.refetch()} />
      ) : (
        <>
          <nav aria-label="Administration">
            <Link to="/admin/jobs" className="underline">
              Jobs
            </Link>
          </nav>
          <p>
            {report.data.start_date} – {report.data.end_date} (UTC), including today so far. As of{' '}
            {report.data.as_of}.
          </p>
          <p className="text-ink-muted">
            Cost is a hypothetical estimate, not billed spend. Estimated calls retain conservative
            reserved usage; denied admissions are excluded. Tokens include cache and reasoning
            tokens once. Quotas use current configured limits and calendar periods, not a rolling
            30-day allowance.
          </p>
          {report.data.providers.length === 0 ? (
            <p>No provider usage or configured quotas.</p>
          ) : (
            report.data.providers.map((provider) => (
              <ProviderReport key={provider.provider} provider={provider} />
            ))
          )}
        </>
      )}
    </main>
  );
}
