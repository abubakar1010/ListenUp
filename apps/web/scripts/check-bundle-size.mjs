// Fails when the JavaScript a first visit downloads is over budget (issue #33:
// initial JavaScript under 200 KB compressed). Run after `pnpm build`.
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { gzipSync } from 'node:zlib';

const BUDGET_BYTES = 200 * 1000;
const dist = new URL('../dist/', import.meta.url).pathname;
const html = readFileSync(join(dist, 'index.html'), 'utf8');

// The entry script plus every module the page preloads; lazy route chunks are excluded.
const files = [
  ...html.matchAll(/<script[^>]+src="\/([^"]+\.js)"/g),
  ...html.matchAll(/<link[^>]+rel="modulepreload"[^>]+href="\/([^"]+\.js)"/g),
].map((match) => match[1]);

let total = 0;
for (const file of new Set(files)) {
  const size = gzipSync(readFileSync(join(dist, file)), { level: 9 }).length;
  total += size;
  console.log(`${(size / 1000).toFixed(1).padStart(8)} kB  ${file}`);
}
console.log(`${(total / 1000).toFixed(1).padStart(8)} kB  initial JavaScript, gzip`);
console.log(`${(BUDGET_BYTES / 1000).toFixed(1).padStart(8)} kB  budget`);

if (files.length === 0) {
  console.error('No entry script found in dist/index.html. Run pnpm build first.');
  process.exit(1);
}
if (total > BUDGET_BYTES) {
  console.error('Initial JavaScript is over budget: split more routes or drop a dependency.');
  process.exit(1);
}
