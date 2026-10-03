/*
 * Inline stroke icons from the design system: 16 px grid, 2 px stroke, currentColor.
 * Decorative by default; give the surrounding control an accessible name.
 */

const base = {
  viewBox: '0 0 16 16',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 2,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
  'aria-hidden': true,
  focusable: false,
} as const;

export function AlertIcon({ className = 'size-5' }: { className?: string }) {
  return (
    <svg {...base} className={className}>
      <path d="M8 2l6.5 12h-13z" />
      <path d="M8 6.5v3M8 12v.01" />
    </svg>
  );
}

export function BackIcon({ className = 'size-4' }: { className?: string }) {
  return (
    <svg {...base} className={className}>
      <path d="M10 3L5 8l5 5" />
    </svg>
  );
}

export function LockIcon({ className = 'size-4' }: { className?: string }) {
  return (
    <svg {...base} className={className}>
      <rect x="3" y="7" width="10" height="7" rx="1.5" />
      <path d="M5 7V5a3 3 0 0 1 6 0v2" />
    </svg>
  );
}

export function CheckIcon({ className = 'size-4' }: { className?: string }) {
  return (
    <svg {...base} className={className}>
      <path d="M3 8.5l3 3 7-7" />
    </svg>
  );
}
