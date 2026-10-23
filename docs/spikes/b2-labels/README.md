# Hand labels for spike #19 (B2): word boundaries

The B2 results report how far each aligner's word boundaries are from a human's. Until these three windows are labelled, they report only how far the systems are from each other (agreement), which is a proxy: two systems can agree and both be wrong.

| Window | Passage | Speech | File time |
| --- | --- | --- | --- |
| `clean-f-1221` | `ls-clean-1221-135767` | LibriSpeech test-clean, female reader | 65 to 125 s |
| `other-m-1688` | `ls-other-1688-142285` | LibriSpeech test-other, male reader | 65 to 125 s |
| `accented-es-20090218` | `vp-accented-20090218-0900-plenary-13-en` | VoxPopuli, Spanish-accented MEP | 65 to 125 s |

**Status (2026-10-22): not labelled yet.** All three `words` tiers are empty, so the B2 gate fails (ADR 0055). `spike-compare` lists incomplete windows and fails the gate until every window in `windows.json` is covered: words, plus `<pause>` intervals, with no unlabelled stretch over 3 s.

`windows.json` defines the windows. Each `NAME.TextGrid` here is a template with an empty `words` tier and a `hint` tier. The hint holds the reference text of the utterances that overlap the window, as text only, with no times from any model, so the labels do not lean towards any of the systems they measure.

## Get the audio

The audio is not in the repository (spikes/.gitignore). Rebuild it from the public corpora; the passage builder is deterministic:

```sh
cd spikes
uv sync --extra datasets
# LibriSpeech test-clean and test-other, VoxPopuli en_accented test: see spikes/README.md
uv run spike-passages librispeech data/raw/LibriSpeech/test-clean data/passages --count 8
uv run spike-passages librispeech data/raw/LibriSpeech/test-other data/passages --count 6
uv run spike-passages voxpopuli data/raw/vp_acc_test_0.parquet data/raw/vp_acc_test_1.parquet \
    data/passages --set vp-accented --count 3
uv run spike-labelkit make data/passages ../docs/spikes/b2-labels/windows.json --audio-out data/labels
```

This writes `data/labels/NAME.wav` (60 s each) and leaves the templates here untouched.

## Label (about 30 to 40 minutes per window in Praat)

1. Open `data/labels/NAME.wav` and `docs/spikes/b2-labels/NAME.TextGrid` in Praat, select both, and choose **View & Edit**.
2. In the `words` tier, put a boundary at the start and the end of every word you hear completely inside the window, and type the word as heard into its interval. Leave short silences empty. Mark a pause longer than 3 s as an interval with the text `<pause>`; otherwise the window counts as incomplete. Skip a word cut off at either edge of the window.
3. Place boundaries where the word's sound begins and ends. Use the spectrogram, not just the waveform: include a plosive's burst, and end a word where its voicing or friction stops. Where two words run together with no gap, share one boundary.
4. Save the TextGrid (text file, long format) over the template.

## Import and measure

```sh
cd spikes
uv run spike-labelkit import ../docs/spikes/b2-labels/windows.json ../docs/spikes/b2-labels
uv run spike-compare data/results/words-v2 --labels ../docs/spikes/b2-labels --out data/results/b2-v2
```

The import writes `PASSAGE.labels.csv` here (word, start, end, in the passage file's time). Commit the labelled TextGrids and the CSV files, then add the "vs hand labels" rows to `docs/spikes/19-b2-alignment.md` and the ADR.

Use newly generated model output from the corrected B2 harness (see the B2 report).
Comparison matches ordered text blocks without using timestamps to choose matches.
Review repeated or ambiguous excerpts, inspect `words_unmatched` and `coverage`, and
require `meets_hand_label_gate: true` and `incomplete windows: none`: all labelled words must match and their mean
boundary error must be <= 50 ms. A missing passage, zero matches, or empty label set
cannot pass. Do not accept a low matched-only mean when coverage is incomplete.
