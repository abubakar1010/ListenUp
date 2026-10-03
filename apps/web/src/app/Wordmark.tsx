import { Link } from 'react-router';

/** No logo exists yet: the wordmark is "ListenUp" in the display face at 800 weight. */
export function Wordmark({ to }: { to: string }) {
  return (
    <Link
      to={to}
      className="rounded-sm font-display text-[1.375rem] leading-7 font-extrabold tracking-[-0.02em] text-ink no-underline hover:text-ink"
    >
      ListenUp
    </Link>
  );
}
