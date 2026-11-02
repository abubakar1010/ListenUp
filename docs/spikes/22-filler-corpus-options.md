# Spike #22 (B4) preparation: openly licensed filler corpus options

- Issue: [#22](https://github.com/abubakar1010/ListenUp/issues/22) (B4: filler-word recall of the disfluency pass). Requirements: FR-SH-4, FR-SH-9, AT-17.
- Governing decision: owner exception **E4** ([#119 comment](https://github.com/abubakar1010/ListenUp/issues/119#issuecomment-6559104401)). B4 runs on public GitHub Arm runners. Workflow logs and artifacts are public, so the audio must be openly licensed and redistributable. Learner, golden-set (#106, #107), YouTube and voice-consent audio are excluded.
- Scope: **research only.** B4 was not run, no application code was written, no audio is committed, and no audio was downloaded. Only text annotation archives and one 44-byte WAV header were fetched, to check formats.
- Research date and every licence check: **2026-11-01**, from this cloud container.

## Answer

**A suitable corpus exists: the AMI Meeting Corpus (CC BY 4.0).** Recommendation: use 20 AMI headset windows of 75 s for B4.

- **Licence and consent.** AMI's audio and its manual annotations are released under CC BY 4.0. Participants signed a consent form for the corpus.
- **Human-marked fillers at word level.** The 40 AMI meetings with the manual disfluency layer mark hesitations (`hesit`, the words *uh* and *um*) and discourse markers (`dm`, including *like* and *you know*) on time-stamped words. The annotators are trained transcribers.
- **Enough material for B4.** All 40 speakers in those meetings have at least one 75 s window in which they speak most of the time and at least 5 of the B4 fillers occur.
- **Run-time fetch is small.** Fetching the 20 windows takes about 48 MB of byte-range requests plus a 23 MB annotation zip.

**Owner decision, 2026-11-02: option A** (AMI as is, with its trained-annotator marks as the reference). #22 says "teacher-marked"; AMI's fillers were marked by trained corpus transcribers and annotators. Option B (a teacher checks the same windows) stays available.

## Requirement used

About 20 English recordings, each 60 to 90 s, of spontaneous or shadowing-like speech. A person has annotated the fillers (um, uh, er, like, you know). Varied speakers and accents are a plus.

A corpus is rejected if any of these hold:
- it forbids redistribution;
- it needs a signed agreement or a paid licence;
- it contains personal data without consent to public release.

Non-commercial (NC) licences are also rejected. B4 decides whether a product feature ships, which is not non-commercial research.

## Candidates

"Primary page" means the licence was read on the corpus owner's own page or its own files on 2026-11-01.

### 1. AMI Meeting Corpus — recommended

| Item | Finding |
| --- | --- |
| Source | University of Edinburgh, AMI Consortium. https://groups.inf.ed.ac.uk/ami/corpus/ |
| Licence (primary page, 2026-11-01) | **CC BY 4.0.** The page https://groups.inf.ed.ac.uk/ami/corpus/license.shtml says "The AMI corpus and its annotations are released under the Creative Commons Attribution 4.0 license". `LICENCE.txt` inside `ami_public_manual_1.6.2.zip` says the same. No registration is needed. |
| Consent | The ethics page (https://groups.inf.ed.ac.uk/ami/corpus/ethicsandconsent.shtml) says the European Commission ethics review covered collection. It refers to "a blank copy of the consent form signed by the participants". The corpus has been distributed publicly by its owner for about 20 years. Participant metadata hold only an ID, sex, age, native language and region. |
| Redistribution and public CI | **Allowed.** CC BY allows sharing and adaptation, including commercial use, with attribution and a note of changes. B4 would still publish only numbers and annotation-derived text, never audio. |
| Speech type | Meetings, about two-thirds of them scenario-based design meetings. The selected windows are mostly one person presenting or explaining. That is spontaneous, monologue-like speech: the closest match to a 75 s Shadow recording among the candidates. |
| Annotation format | NXT XML (ISO-8859-1). `words/<meeting>.<agent>.words.xml` holds `<w>` elements with `starttime` and `endtime` in seconds. `disfluency/<meeting>.<agent>.disfluency.xml` holds `<dsfl>` elements that point to word ids, with types in `ontologies/dsfl-types.xml`: `ami_dsfl_5` is `hesit` (Hesitation) and `ami_dsfl_3` is `dm` (Discourse Marker). |
| Word-level fillers? | **Yes**, in the 40 meetings that have the disfluency layer (ES2002, ES2005, ES2006, ES2008, IS1001, IS1003, IS1009, TS3005, TS3006, TS3007; sessions a to d). Counted in this research: 7,266 hesitation-tagged *uh*/*um*/*er* words, and 681 discourse-marker-tagged *like* (370) and *you know* (311) occurrences. The `dm` tag separates filler *like* from the verb *like*. That fixes the false positive #20 saw from a plain word match. |
| Spelling of fillers | The AMI transcription rules (https://groups.inf.ed.ac.uk/ami/corpus/regularised_spellings.shtml) spell every pure-vowel hesitation as *uh*, so British *er* appears as *uh* (only 1 *er* occurs). Hesitation with a nasal is *um*, and a pure nasal is *mm*. B4 must treat *er*, *uh* and *ah* as one class when matching. |
| Size, speakers and accents | 100 h and 171 meetings in the full corpus. The disfluency layer covers 40 meetings and 40 speakers: 15 women and 25 men. Native English speakers from England, Scotland, Northern Ireland, the USA, Canada, Australia, India and Singapore. Non-native speakers whose first languages are French, Hindi, Tamil, Telugu, Estonian, Greek, Wolof, Swiss German, Chinese and Dutch. TNO speakers have no metadata record; their IDs mark them as Dutch. |
| Audio | One WAV per headset channel: `https://groups.inf.ed.ac.uk/ami/AMICorpusMirror/amicorpus/<meeting>/audio/<meeting>.Headset-<n>.wav`. Each is PCM, 16 kHz, mono, 16-bit, with a 44-byte header (checked on `ES2002a.Headset-0.wav`). A whole file is 41 to 107 MB. The server sends `Accept-Ranges: bytes` and answers range requests with 206. |
| Download and run-time fetch | 1. Annotations: `https://groups.inf.ed.ac.uk/ami/AMICorpusAnnotations/ami_public_manual_1.6.2.zip`, 22,887,865 bytes. Pin its SHA-256 in the fetch script.<br>2. Audio: a range request per window, bytes `44 + 32000·t0` to `44 + 32000·(t0 + 75) − 1`. That is 2.4 MB per window, about 48 MB for 20. Write a fresh WAV header locally, and pin each range's SHA-256 in a committed text manifest.<br>3. Fall back to whole files (about 1.4 GB for 20) only if range requests fail.<br>Keep everything in the job's workspace, as `docs/spikes/shadow20/fetch.py` does: no artifact upload, no cache of audio. |

**Proposed 20 windows.** The selection rule is fixed before B4 runs and does not maximise filler counts:

1. Consider 75 s windows that start at a word onset. In each, the target speaker speaks for at least 60% of the time, and at least 5 B4 fillers occur (*uh*, *um*, *er*, and `dm`-tagged *like* or *you know*).
2. Per speaker, take the window with the least speech from other speakers (crosstalk), compared in steps of 1% of the window (0.75 s). On a tie, take the one with more own speech, then the earliest.
3. Take speakers in the same order, with at most 4 TNO (Dutch) speakers.

Running the rule on `ami_public_manual_1.6.2` gives 230 marked fillers: 222 *uh*/*um* and 8 *like*/*you know*. It gives 9 women and 11 men. The table comes from the implementation (`spikes/src/listenup_spikes/ami.py`, branch `feat/22-b4-benchmark-workflow`); the committed manifest that the B4 workflow generates is the final list.

| # | Speaker | First language / region | Meeting | File | Start (s) | Own speech | Crosstalk | uh/um | like/you know |
| - | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | FIO089 | Swiss German / America | IS1009c | Headset-3 | 1386.41 | 1.00 | 0.00 | 9 | 1 |
| 2 | MTD026UID | Dutch (TNO) | TS3007d | Headset-2 | 258.13 | 1.00 | 0.00 | 19 | 0 |
| 3 | MTD025PM | Dutch (TNO) | TS3007b | Headset-0 | 83.15 | 0.99 | 0.00 | 28 | 0 |
| 4 | MTD017PM | Dutch (TNO) | TS3005a | Headset-0 | 209.01 | 0.99 | 0.00 | 15 | 0 |
| 5 | MTD022ID | Dutch (TNO) | TS3006c | Headset-2 | 403.97 | 0.99 | 0.00 | 11 | 1 |
| 6 | FIO084 | Telugu / Scotland | IS1009c | Headset-2 | 986.39 | 0.98 | 0.00 | 5 | 0 |
| 7 | FEE030 | English / USA | ES2008b | Headset-1 | 1010.66 | 0.97 | 0.00 | 5 | 1 |
| 8 | MEO022 | English / India | ES2006b | Headset-0 | 290.46 | 0.97 | 0.00 | 15 | 0 |
| 9 | MEE031 | English / England | ES2008b | Headset-2 | 720.05 | 0.97 | 0.00 | 7 | 1 |
| 10 | MEO020 | Hindi / UK | ES2005b | Headset-1 | 169.56 | 0.97 | 0.00 | 10 | 1 |
| 11 | MEE008 | English / Canada | ES2002c | Headset-3 | 356.72 | 0.94 | 0.00 | 10 | 1 |
| 12 | FEE029 | English / USA | ES2008a | Headset-0 | 32.58 | 0.93 | 0.00 | 7 | 0 |
| 13 | FIE088 | English | IS1009d | Headset-0 | 134.85 | 0.93 | 0.00 | 5 | 0 |
| 14 | MIO043 | French | IS1001c | Headset-0 | 48.31 | 0.89 | 0.00 | 13 | 0 |
| 15 | FIO087 | Tamil | IS1009b | Headset-1 | 1415.28 | 0.84 | 0.00 | 8 | 0 |
| 16 | MIO035 | Chinese | IS1003b | Headset-3 | 181.17 | 0.76 | 0.00 | 9 | 0 |
| 17 | FIO017 | French / England | IS1003a | Headset-0 | 85.57 | 0.75 | 0.00 | 9 | 0 |
| 18 | FEE021 | English / Australia | ES2006a | Headset-2 | 920.53 | 0.63 | 0.00 | 5 | 0 |
| 19 | FEO023 | Estonian / UK | ES2006b | Headset-3 | 802.18 | 0.99 | 0.01 | 13 | 0 |
| 20 | MEE006 | English / Singapore, Canada | ES2002c | Headset-0 | 957.91 | 0.98 | 0.01 | 19 | 2 |

"File" uses the speaker's `channel` from `corpusResources/meetings.xml`. Before measuring, the B4 workflow should confirm that this channel's energy is higher than the other headsets' during the speaker's own words.

**Limits B4 must state:**
- **Too few *like* and *you know* for a separate figure.** There are only 8 in the selection: a figure for those two words is indicative only, not a measurement. Report *uh*/*um* and *like*/*you know* separately, as well as the total. Discourse markers are rare in AMI (681 against 7,266 hesitations), so a better *like*/*you know* test would need a supplementary set; the rule was not tuned to raise the count.
- **Annotators were not teachers.** See the owner decision above.
- **Not phone audio.** The recordings are headset audio from 2005 with crosstalk near zero. They are cleaner than a learner's phone, so recall may be optimistic.
- **Meetings, not shadowing.** Shadowing repeats a model passage; these speakers produce their own words. Filler behaviour is natural, but the content differs.
- **Attribution.** Credit the AMI Consortium, link CC BY 4.0, and state the changes (75 s excerpts, resampled if needed) in the workflow README and the results.

### 2. ICSI Meeting Corpus — acceptable backup

| Item | Finding |
| --- | --- |
| Source | ICSI Berkeley, distributed by the University of Edinburgh. https://groups.inf.ed.ac.uk/ami/icsi/ |
| Licence (primary page, 2026-11-01) | **CC BY 4.0.** https://groups.inf.ed.ac.uk/ami/icsi/license.shtml says "The ICSI corpus and its annotations are released under the Creative Commons Attribution 4.0 license agreement". |
| Redistribution and public CI | Allowed, with attribution. |
| Annotation format | NXT XML (`ICSI_core_NXT.zip`, 19 MB), with `Words/<meeting>.<agent>.words.xml` and `<w starttime endtime>`. Some words have blank start or end times. The original MRT transcripts are also offered. |
| Word-level fillers? | **Partly.** *uh* and *um* are transcribed as words: this research counted 19,950 *uh*/*um* and 48 *er* in the core annotations. There is no word-level tag that separates filler *like* or *you know* from other uses, and some words lack timestamps. |
| Size, speakers and accents | About 70 h in 75 meetings. Most speakers are ICSI researchers, native and non-native, mostly American English. Natural research meetings with more crosstalk than AMI's presentations. |
| Download and run-time fetch | Headset SPH files are chosen through a form (`https://homepages.inf.ed.ac.uk/cgi/simonk/ICSI/estimate.cgi`) that produces a download script. The direct-URL pattern was not verified. A workflow would pin the URL list and checksums that the form produces. |

**Why it is the backup.** Its licence is as good as AMI's, but it covers only *uh*/*um*, has gaps in word timing, and offers fewer accents.

### 3. Santa Barbara Corpus of Spoken American English (SBCSAE) — legal but weaker

| Item | Finding |
| --- | --- |
| Source | UC Santa Barbara (John W. Du Bois). https://www.linguistics.ucsb.edu/research/santa-barbara-corpus-spoken-american-english. TalkBank mirror: https://talkbank.org/ca/access/SBCSAE.html |
| Licence (primary page, 2026-11-01) | **CC BY-ND 3.0 US.** The page says "SBCSAE by John W. Du Bois is licensed under a Creative Commons Attribution-No Derivative Works 3.0 United States License". |
| Redistribution and public CI | Unchanged redistribution is allowed. Under ND, cut excerpts must never be shared. That is workable, because B4 never uploads audio, but it is one more rule to police. |
| Personal data | UCSB replaced names with pseudonyms and low-pass filtered some passages at 400 Hz. Filtered passages would distort a filler test. |
| Annotation format | `SBCorpus.zip` (1.26 MB) holds `.trn` files: tab-separated start and end times per intonation unit, then the text. Fillers are written inline (counted here: 1,836 *uh*, 550 *um*, 23 *er*, 1,524 *you know*, across all `.trn` files in the zip). |
| Word-level fillers? | **No.** Timing is per intonation unit, about 1 to 2 s. *you know* and *like* are not tagged as discourse markers. |
| Size, speakers and accents | 60 conversations, about 249,000 words. American English only. |
| Download and run-time fetch | Audio is shared per conversation through `ucsb.box.com` links, which are hard to script. The TalkBank media mirror linked from the page (`https://talkbank.org/media/CABank/SBCSAE/`) returned **404** from this container, and `media.talkbank.org` **failed TLS verification** through the session proxy (host reported; no proxy or TLS setting was changed). |

### 4. Earnings-22 (Rev) — not recommended

| Item | Finding |
| --- | --- |
| Source | Rev.com. https://github.com/revdotcom/speech-datasets (earnings22). HF mirror: `distil-whisper/earnings22`. |
| Licence (primary source file, 2026-11-01) | **CC BY-SA 4.0**, from the badge in `earnings22/README.md`, read via raw.githubusercontent.com. github.com itself returned **403** to curl from this container. |
| Redistribution and public CI | Allowed by the stated licence. However, the recordings are companies' earnings calls, and the README does not say how Rev obtained the right to relicense them. |
| Annotation format | Pipe-separated `.nlp` token files. They have `ts` and `endTs` columns, but these are empty in the README example; the HF mirror's timings come from wav2vec2 and are segment-level. Transcripts keep *uh* and *um* verbatim. |
| Word-level fillers? | **No** human word timing, and no filler tag for *like* or *you know*. |
| Size, speakers and accents | 125 calls, 119 h, speakers from 27 countries. Prepared remarks are read aloud; only the Q&A is spontaneous. |
| Download | 25.9 GB as parquet on HF, or the original MP3s on GitHub (LFS). |

### Rejected

| Corpus | Source checked (2026-11-01) | Why rejected |
| --- | --- | --- |
| PodcastFillers (Adobe) | Zenodo record 7121457 (licence field `cc-nc`) and https://podcastfillers.github.io/ | The metadata licence (Adobe) allows use "for noncommercial research purposes only" and forbids deploying technology built with it in commercial applications. Each episode's audio has its own CC licence. It covers only *uh*/*um*. 25 GB in split zips. |
| CORAAL | https://oraal.github.io/coraal | CC BY-NC-SA 4.0: non-commercial. |
| DisfluencySpeech (`amaai-lab`) | Hugging Face dataset card (`apache-2.0` in metadata) | One speaker performs Switchboard transcripts, which are LDC-licensed text, so the text's provenance is unclear. Short acted utterances, not 60 to 90 s of spontaneous speech. |
| Common Voice Spontaneous Speech (English) | mozilladatacollective.com (the page needs JavaScript and did not load). CC0 and the size come from search results, not the primary page. | Clips average about 10 s (18.38 h over 6,382 clips), far below 60 to 90 s. Filler transcription conventions are undocumented. |
| Switchboard / Fisher (LDC) | https://catalog.ldc.upenn.edu/LDC97S62 | Needs the LDC User Agreement and a fee. |
| Buckeye Corpus | `buckeyecorpus.osu.edu` **failed TLS verification** through the session proxy. Terms come from search results of its `License.pdf` and FAQ. | Needs a signed licence per lab, for research and education only, with no derivative works and password-protected hosting. |

Not examined in detail: LibriSpeech, TED-LIUM, VoxPopuli and GigaSpeech. They hold read or edited speech, or their transcripts remove fillers, so they cannot answer B4 whatever their licence.

## Owner options

| Option | What | Effort | Notes |
| --- | --- | --- | --- |
| **A. AMI as is (recommended)** | Use the 20 windows above with AMI's own word-level marks as the reference. | About 0.5 day inside #22: fetch script, window manifest, scoring. | Fully open; no recording or annotation work. "Teacher-marked" becomes "trained-annotator-marked". |
| **B. AMI plus teacher check** | A teacher listens to the same 20 open windows and confirms, adds or removes filler marks in ELAN or Praat, starting from the AMI marks. The corrected marks are committed as text under CC BY 4.0. | About 5 to 6 teacher-hours (about 15 min per 75 s clip), plus about 1.5 h for a second pass on 5 clips to measure agreement. About 0.5 day of setup. | Meets "teacher-marked" literally with no new personal data. Only the derived annotations are committed, never audio. |
| **C. Team recordings plus teacher annotation** | 10 to 20 team members each record one or two 75 s spontaneous or shadowing-style takes. Each person signs a written consent to public release under CC BY 4.0 (or CC0). The audio is hosted openly, for example as a Zenodo or Hugging Face dataset, and fetched at run time. A teacher annotates fillers at word level. | Consent form and hosting: about 1 day. Recording: about 15 min per person. Annotation: about 5 to 6 teacher-hours, plus about 1.5 h for agreement. Total about 2.5 to 3 person-days spread over a week. | Closest to real learner conditions (phone microphones, shadowing). Accent variety is limited to the team. Publishing the voices is permanent, so consent must say so plainly. |
| D. ICSI as is | Like A, with ICSI. | About 1 day, because the download is form-based. | Only *uh*/*um*, so *like* and *you know* go untested. |

**Recommendation:** option A, so B4 can start as soon as the shared benchmark workflow exists. Add option B if the owner wants AT-17 evidence marked by a teacher. Keep option C for the later stage-0 spot check, or if learner-like microphone conditions turn out to change recall.

## Reproducing this research

The analysis read only the text annotations. The rule is implemented and tested in `spikes/src/listenup_spikes/ami.py` (`spike-ami manifest`). By hand, the steps are:
1. Download `ami_public_manual_1.6.2.zip`.
2. For each `disfluency/*.xml` meeting and agent, expand the `dsfl` children of types `ami_dsfl_5` and `ami_dsfl_3` to word ids.
3. Keep words whose text is *uh*, *um*, *er* or *erm* (hesitation) or *like* or *know* (discourse marker; *you know* counts once).
4. Slide a 75 s window from each word onset and apply the selection rule above.

Speaker metadata come from `corpusResources/participants.xml` and channels from `corpusResources/meetings.xml`. The B4 workflow PR should commit the rule as code and the resulting manifest as text.
