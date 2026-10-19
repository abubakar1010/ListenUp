import { render, screen, within } from '@testing-library/react';

import { formatAccuracy } from './accuracy';
import { DictationDiff } from './DictationDiff';
import { RESULT } from './fixtures';

function itemFor(text: string) {
  return screen.getByText(text, { exact: false }).closest('li') as HTMLElement;
}

test('shows the accuracy percentage and the count of each status', () => {
  render(<DictationDiff result={RESULT} />);

  expect(screen.getByText('90%')).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: /accuracy/i })).toBeInTheDocument();
  const summary = screen.getByRole('list', { name: 'Summary' });
  expect(summary).toHaveTextContent('8 correct');
  expect(summary).toHaveTextContent('1 spelling slip');
  expect(summary).toHaveTextContent('0 wrong');
  expect(summary).toHaveTextContent('1 missing');
  expect(summary).toHaveTextContent('1 extra');
});

test('formats accuracy without needless decimals', () => {
  expect(formatAccuracy(90)).toBe('90%');
  expect(formatAccuracy(66.67)).toBe('66.67%');
  expect(formatAccuracy(0)).toBe('0%');
});

test('every status that is not correct has a text label as well as a colour', () => {
  render(<DictationDiff result={RESULT} />);
  const diff = screen.getByRole('list', { name: 'Word by word' });

  expect(within(itemFor('street')).getByText('Spelling slip')).toBeInTheDocument();
  expect(within(itemFor('to')).getByText('Missing')).toBeInTheDocument();
  expect(within(itemFor('cool')).getByText('Wrong')).toBeInTheDocument();
  expect(within(itemFor('quickly')).getByText('Extra')).toBeInTheDocument();
  // A correct word needs no label, but reads as plain text.
  expect(within(diff).getByText('Cities').closest('li')).not.toHaveTextContent(/correct/i);
});

test('wrong, missing and extra words also say what the learner typed', () => {
  render(<DictationDiff result={RESULT} />);

  expect(itemFor('street')).toHaveTextContent('you typed streat');
  expect(itemFor('cool')).toHaveTextContent('you typed cold');
  expect(itemFor('to')).toHaveTextContent('you typed nothing');
});

test('statuses differ by line style, not only by colour', () => {
  render(<DictationDiff result={RESULT} />);

  const styleOf = (text: string) =>
    within(itemFor(text)).getByText(text, { exact: false, selector: '[data-word]' }).className;
  const styles = ['street', 'to', 'cool', 'quickly'].map(styleOf);

  expect(new Set(styles).size).toBe(4);
  expect(styleOf('street')).toContain('decoration-dotted');
  expect(styleOf('to')).toContain('decoration-dashed');
  expect(styleOf('cool')).toContain('decoration-wavy');
  expect(styleOf('quickly')).toContain('line-through');
});

test('a legend explains each label', () => {
  render(<DictationDiff result={RESULT} />);

  const legend = screen.getByRole('list', { name: 'Key' });
  for (const label of ['Spelling slip', 'Missing', 'Wrong', 'Extra']) {
    expect(within(legend).getByText(label)).toBeInTheDocument();
  }
});
