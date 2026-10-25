/*
 * Colours come from the design tokens in index.css (bg-accent, text-danger, ...).
 * Tailwind's palette colours bypass them and drift between themes (#197).
 */
const PALETTE =
  /\b(?:bg|text|border|outline|ring|fill|stroke|from|to|via|decoration)-(?:slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-\d{2,3}\b/;

const SOURCES = import.meta.glob<string>(
  ['./**/*.{ts,tsx}', '!./**/*.test.{ts,tsx}', '!./api/**'],
  {
    query: '?raw',
    import: 'default',
    eager: true,
  },
);

test('no source file uses a Tailwind palette colour instead of a design token', () => {
  const offenders = Object.entries(SOURCES)
    .map(([path, text]) => ({ path, match: PALETTE.exec(text)?.[0] }))
    .filter((found) => found.match)
    .map((found) => `${found.path}: ${found.match}`);

  expect(Object.keys(SOURCES).length).toBeGreaterThan(50);
  expect(offenders).toEqual([]);
});
