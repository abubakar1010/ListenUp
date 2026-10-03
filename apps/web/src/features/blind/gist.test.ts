import { countSentences, sentenceStatus } from './gist';

// The same cases as the server's tests/unit/blind/test_gist.py.
test.each([
  ['', 0],
  ['The speaker talks about trees', 0],
  ['The speaker talks about trees.', 1],
  ['Trees cool streets. Shade lowers heat! Do roots break pipes?', 3],
  ['Trees cool streets.Shade lowers heat.', 1],
  ['Yes. No. Trees cool streets.', 1],
  ["It's well-known that trees help. They cost money... Cities plant them anyway!", 3],
  ['The tree is 3.5 metres tall. It grows fast in rain.', 2],
  ['Mr. Smith plants trees. He likes oaks a lot.', 2],
  ['Trees cool streets.\nShade lowers heat.\n\nRoots need space.', 3],
  ['Trees cool streets. Shade lowers heat. Roots need', 2],
  ['... . ! ?', 0],
])('%j has %i sentences', (text, expected) => {
  expect(countSentences(text)).toBe(expected);
});

test('the status says what is missing', () => {
  expect(sentenceStatus(0)).toBe('0 of 3 sentences. Write 3 more.');
  expect(sentenceStatus(2)).toBe('2 of 3 sentences. Write one more.');
  expect(sentenceStatus(3)).toBe('3 sentences. Ready to submit.');
});
