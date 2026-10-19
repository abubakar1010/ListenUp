/** "90%" or "66.67%": two decimals at most, none when whole. */
export function formatAccuracy(accuracy: number): string {
  return `${new Intl.NumberFormat('en', { maximumFractionDigits: 2 }).format(accuracy)}%`;
}
