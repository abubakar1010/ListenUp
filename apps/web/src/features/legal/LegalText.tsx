import type { ReactNode } from 'react';
import { Link } from 'react-router';

/**
 * Renders a legal text from docs/legal (#103, ADR 0051). Only the subset those files
 * use: `#` to `###` headings, paragraphs, `- ` lists, `> ` notes, `**bold**` and
 * `[links](/path or https://…)`. A link to anything else stays plain text.
 */
export function LegalText({ source }: { source: string }) {
  const blocks = source.trim().split(/\n\s*\n/);
  return <>{blocks.map((block, index) => renderBlock(block.trim(), index))}</>;
}

const HEADINGS = {
  1: 'font-display text-title-compact',
  2: 'mt-4 font-display text-heading',
  3: 'mt-2 font-bold',
} as const;

function renderBlock(block: string, key: number): ReactNode {
  const lines = block.split('\n').map((line) => line.trim());
  const heading = /^(#{1,3}) (.*)$/.exec(block);
  if (heading) {
    const level = heading[1].length as 1 | 2 | 3;
    const Tag = `h${level}` as const;
    return (
      <Tag key={key} className={HEADINGS[level]}>
        {renderInline(heading[2])}
      </Tag>
    );
  }
  if (lines.every((line) => line.startsWith('- '))) {
    return (
      <ul key={key} className="flex list-disc flex-col gap-1 pl-6">
        {lines.map((line, index) => (
          <li key={index}>{renderInline(line.slice(2))}</li>
        ))}
      </ul>
    );
  }
  if (lines.every((line) => line.startsWith('>'))) {
    const text = lines.map((line) => line.replace(/^>\s?/, '')).join(' ');
    return (
      <p key={key} role="note" className="rounded-md border border-line bg-surface-raised p-4">
        {renderInline(text)}
      </p>
    );
  }
  return <p key={key}>{renderInline(lines.join(' '))}</p>;
}

// An app path starts with one `/`; `//host` and `/\host` would leave the app.
const APP_PATH = /^\/(?![/\\])/;
// A link target may hold one level of parentheses, as URLs sometimes do.
const INLINE = /\*\*(.+?)\*\*|\[([^\]]+)\]\(((?:[^()\s]|\([^()\s]*\))+)\)/g;

function renderInline(text: string): ReactNode[] {
  const parts: ReactNode[] = [];
  let last = 0;
  for (const match of text.matchAll(INLINE)) {
    parts.push(text.slice(last, match.index));
    const [, bold, label, href] = match;
    if (bold !== undefined) {
      parts.push(<strong key={match.index}>{bold}</strong>);
    } else if (APP_PATH.test(href)) {
      parts.push(
        <Link key={match.index} to={href} className="text-accent underline">
          {label}
        </Link>,
      );
    } else if (/^https?:\/\//.test(href)) {
      parts.push(
        <a key={match.index} href={href} rel="noreferrer" className="text-accent underline">
          {label}
        </a>,
      );
    } else {
      parts.push(label);
    }
    last = match.index + match[0].length;
  }
  parts.push(text.slice(last));
  return parts;
}
