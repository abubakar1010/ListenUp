import type { ReactNode } from 'react';

import { inputClass } from '../../components/field';
import type { MarkTag } from './markSync';
import { TAG_LABELS, TAGS } from './tags';

/**
 * The optional tag of a mark (#61): a native select, so mouse, touch and keyboard all work
 * and assistive technology reads its name and the chosen tag. "No tag" clears it.
 */
export function TagSelect({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  /** The visible label; it may hold hidden words that name the mark. */
  label: ReactNode;
  value: MarkTag | null;
  onChange: (tag: MarkTag | null) => void;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <label htmlFor={id} className="font-bold">
        {label}
      </label>
      <select
        id={id}
        className={inputClass}
        value={value ?? ''}
        onChange={(event) => onChange((event.target.value as MarkTag) || null)}
      >
        <option value="">No tag</option>
        {TAGS.map((tag) => (
          <option key={tag} value={tag}>
            {TAG_LABELS[tag]}
          </option>
        ))}
      </select>
    </div>
  );
}
