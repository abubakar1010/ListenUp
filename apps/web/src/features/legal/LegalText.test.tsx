import { screen, within } from '@testing-library/react';

import { renderWithProviders } from '../../test-utils';
import { LegalText } from './LegalText';

const SOURCE = `# Privacy Policy

Version privacy-2026-1,
draft.

> **Draft, not yet legally reviewed.** It may change.

## What we keep

- Your **email** address.
- See the [voice notice](/voice-consent).

Read [the source](https://example.com/x) or [this](javascript:alert(1)).`;

test('renders headings, paragraphs and lists from the legal text', () => {
  renderWithProviders(<LegalText source={SOURCE} />);

  expect(screen.getByRole('heading', { level: 1, name: 'Privacy Policy' })).toBeInTheDocument();
  expect(screen.getByRole('heading', { level: 2, name: 'What we keep' })).toBeInTheDocument();
  // Lines of one paragraph join with a space.
  expect(screen.getByText('Version privacy-2026-1, draft.')).toBeInTheDocument();
  const items = within(screen.getByRole('list')).getAllByRole('listitem');
  expect(items.map((item) => item.textContent)).toEqual([
    'Your email address.',
    'See the voice notice.',
  ]);
  expect(within(items[0]).getByText('email').tagName).toBe('STRONG');
});

test('shows a quoted block as a note', () => {
  renderWithProviders(<LegalText source={SOURCE} />);

  const note = screen.getByRole('note');
  expect(note).toHaveTextContent('Draft, not yet legally reviewed. It may change.');
  expect(within(note).getByText('Draft, not yet legally reviewed.').tagName).toBe('STRONG');
});

test('links to app pages and web addresses, and leaves any other link as text', () => {
  renderWithProviders(<LegalText source={SOURCE} />);

  expect(screen.getByRole('link', { name: 'voice notice' })).toHaveAttribute(
    'href',
    '/voice-consent',
  );
  expect(screen.getByRole('link', { name: 'the source' })).toHaveAttribute(
    'href',
    'https://example.com/x',
  );
  expect(screen.queryByRole('link', { name: 'this' })).not.toBeInTheDocument();
  expect(screen.getByText(/^Read/)).toHaveTextContent('Read the source or this.');
});

test.each(['//evil.example/x', '/\\evil.example', 'HTTP:x', 'mailto:a@b.c'])(
  'leaves the link target %s as text, since it is neither an app path nor a web address',
  (href) => {
    renderWithProviders(<LegalText source={`See [elsewhere](${href}).`} />);

    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(screen.getByText('See elsewhere.')).toBeInTheDocument();
  },
);
