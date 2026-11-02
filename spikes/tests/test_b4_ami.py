"""B4 (#22) on AMI: reading the human filler marks, choosing windows, fetching audio ranges."""

import hashlib
import io
import json
import struct
import wave
import zipfile
from pathlib import Path

import pytest

from listenup_spikes.ami import (
    ANNOTATIONS_SHA256,
    Track,
    Window,
    Word,
    best_window,
    check_wav_header,
    choose_windows,
    fetch_all,
    fetch_annotations,
    fetch_window,
    filler_marks,
    manifest_entry,
    parse_words,
    pcm_byte_range,
    range_get,
    speakers,
    tracks_from_zip,
    validate_manifest,
)
from listenup_spikes.metrics import FillerMark

WORDS = b"""<?xml version="1.0" encoding="ISO-8859-1" standalone="yes"?>
<nite:root nite:id="X.A.words" xmlns:nite="http://nite.sourceforge.net/">
   <w nite:id="X.A.words0" starttime="1.0" endtime="1.3">Um</w>
   <w nite:id="X.A.words1" starttime="1.3" endtime="1.3" punc="true">,</w>
   <w nite:id="X.A.words2" starttime="1.4" endtime="1.6">you</w>
   <w nite:id="X.A.words3" starttime="1.6" endtime="1.8">know</w>
   <w nite:id="X.A.words4" starttime="1.8" endtime="2.0">I</w>
   <w nite:id="X.A.words5" starttime="2.0" endtime="2.2">like</w>
   <w nite:id="X.A.words6" starttime="2.2" endtime="2.5">it</w>
   <w nite:id="X.A.words7" starttime="2.5" endtime="2.7">mm</w>
   <w nite:id="X.A.words8" starttime="2.7" endtime="2.9">like</w>
   <w nite:id="X.A.words9" starttime="2.9" endtime="3.1">so</w>
   <w nite:id="X.A.words10" starttime="3.1" endtime="3.3">uh</w>
   <vocalsound nite:id="X.A.vs1" starttime="3.3" endtime="3.5" type="laugh"/>
   <w nite:id="X.A.words11" starttime="" endtime="">er</w>
</nite:root>
"""

DISFLUENCY = b"""<?xml version="1.0" encoding="ISO-8859-1" standalone="yes"?>
<nite:root nite:id="X.A.disfluency" xmlns:nite="http://nite.sourceforge.net/">
   <dsfl nite:id="d1">
      <nite:pointer role="dsfl-type" href="dsfl-types.xml#id(ami_dsfl_5)"/>
      <nite:child href="X.A.words.xml#id(X.A.words0)"/>
   </dsfl>
   <dsfl nite:id="d2">
      <nite:pointer role="dsfl-type" href="dsfl-types.xml#id(ami_dsfl_3)"/>
      <nite:child href="X.A.words.xml#id(X.A.words2)..id(X.A.words3)"/>
   </dsfl>
   <dsfl nite:id="d3">
      <nite:pointer role="dsfl-type" href="dsfl-types.xml#id(ami_dsfl_5)"/>
      <nite:child href="X.A.words.xml#id(X.A.words7)"/>
   </dsfl>
   <dsfl nite:id="d4">
      <nite:pointer role="dsfl-type" href="dsfl-types.xml#id(ami_dsfl_3)"/>
      <nite:child href="X.A.words.xml#id(X.A.words8)..id(X.A.words9)"/>
   </dsfl>
   <dsfl nite:id="d5">
      <nite:pointer role="dsfl-type" href="dsfl-types.xml#id(ami_dsfl_8)"/>
      <nite:child href="X.A.words.xml#id(X.A.words10)"/>
   </dsfl>
   <dsfl nite:id="d6">
      <nite:pointer role="dsfl-type" href="dsfl-types.xml#id(ami_dsfl_5)"/>
      <nite:child href="X.A.words.xml#id(X.A.words11)"/>
   </dsfl>
</nite:root>
"""


def test_parse_words_keeps_timed_words_and_drops_punctuation() -> None:
    words = parse_words(WORDS)
    assert [w.text for w in words] == [
        "um",
        "you",
        "know",
        "i",
        "like",
        "it",
        "mm",
        "like",
        "so",
        "uh",
    ]
    assert (words[0].id, words[0].start, words[0].end) == ("X.A.words0", 1.0, 1.3)


def test_filler_marks_take_every_hesitation_word_and_tagged_discourse_markers() -> None:
    marks = filler_marks(WORDS, DISFLUENCY)
    assert marks == [
        FillerMark(1.0, 1.3, "hesitation", "um"),
        FillerMark(1.4, 1.8, "discourse", "you know"),  # one mark for the pair
        FillerMark(2.7, 2.9, "discourse", "like"),  # the tagged "like", not the verb at 2.0
        # Transcribers wrote it, so it was spoken: a hesitation even though the annotators
        # tagged it as an omission (20% of AMI's hesitation words carry no hesitation tag).
        FillerMark(3.1, 3.3, "hesitation", "uh"),
    ]
    # Not marks: "mm" (not a B4 filler), "so" (a discourse marker outside B4's list) and
    # the untimed "er".


def test_a_discourse_span_ending_on_punctuation_still_counts() -> None:
    words = b"""<nite:root xmlns:nite="http://nite.sourceforge.net/">
   <w nite:id="Y.words0" starttime="4.0" endtime="4.2">you</w>
   <w nite:id="Y.words1" starttime="4.2" endtime="4.4">know</w>
   <w nite:id="Y.words2" starttime="4.4" endtime="4.4" punc="true">,</w>
</nite:root>"""
    span = b"""<nite:root xmlns:nite="http://nite.sourceforge.net/"><dsfl nite:id="d">
   <nite:pointer role="dsfl-type" href="dsfl-types.xml#id(ami_dsfl_3)"/>
   <nite:child href="Y.words.xml#id(Y.words0)..id(Y.words2)"/>
</dsfl></nite:root>"""
    assert filler_marks(words, span) == [FillerMark(4.0, 4.4, "discourse", "you know")]


def track(
    speaker: str = "MEE001",
    word_every_s: float = 1.0,
    filler_times: tuple[float, ...] = (10, 20, 30, 40, 50, 100, 110, 120, 130, 140),
    others: tuple[tuple[float, float], ...] = ((0.0, 60.0),),
    duration: float = 200.0,
) -> Track:
    words, t = [], 0.0
    while t < 200:
        words.append(Word(f"w{t}", t, t + 0.8, "word"))
        t += word_every_s
    marks = [FillerMark(t, t + 0.3, "hesitation", "um") for t in filler_times]
    return Track("ES2002a", "A", speaker, 0, words, marks, list(others), duration)


def test_best_window_prefers_no_crosstalk_then_the_earliest_start() -> None:
    window = best_window(track())
    assert window is not None
    # Windows starting before 60 s overlap the other speaker; from 66 s on, a 75 s window
    # holds the five fillers at 100 to 140 s (the last one ends at 140.3 s).
    assert (window.start, window.crosstalk) == (66.0, 0.0)
    assert window.own == 0.8
    assert [m.start for m in window.marks] == [34.0, 44.0, 54.0, 64.0, 74.0]
    assert window.name == "ES2002a-MEE001"


def test_best_window_counts_crosstalk_when_every_window_has_some() -> None:
    window = best_window(track(others=((0.0, 200.0),)))
    assert window is not None and window.crosstalk == 1.0


def test_best_window_ends_before_the_recording_does() -> None:
    # The recording ends at 140.5 s, so no window can reach the fillers at 100 to 140 s;
    # the best one left covers 10 to 50 s, despite its crosstalk.
    window = best_window(track(duration=140.5))
    assert window is not None
    assert window.start == 10.0 and window.start + window.length <= 140.5


def test_best_window_needs_five_fillers() -> None:
    assert best_window(track(filler_times=(100, 110, 120, 130))) is None


def test_best_window_needs_the_speaker_talking_most_of_the_time() -> None:
    # 0.8 s of speech every 1.5 s is 53% of the window: below the 60% floor.
    assert best_window(track(word_every_s=1.5)) is None
    assert best_window(track(word_every_s=1.3)) is not None  # 61%


def window(speaker: str, crosstalk: float, own: float = 0.9) -> Window:
    return Window("M", "A", speaker, 0, 0.0, 75.0, own, crosstalk, ())


def test_choose_windows_takes_one_per_speaker_least_crosstalk_first() -> None:
    chosen = choose_windows(
        [
            window("FEE001", 0.2),
            window("MEE002", 0.0),
            window("FEE001", 0.05),
            window("MIO003", 0.0, own=0.95),
            window("FIE004", 0.1),
        ],
        count=3,
    )
    assert [(w.speaker, w.crosstalk) for w in chosen] == [
        ("MIO003", 0.0),  # tie on crosstalk: more own speech first
        ("MEE002", 0.0),
        ("FEE001", 0.05),
    ]


def test_choose_windows_caps_the_dutch_tno_speakers() -> None:
    dutch = [window(f"MTD00{i}PM", 0.0) for i in range(6)]
    chosen = choose_windows([*dutch, window("FEE001", 0.3), window("MIO002", 0.4)], count=6)
    speakers = [w.speaker for w in chosen]
    assert sum(s[2] == "D" for s in speakers) == 4
    assert speakers[-2:] == ["FEE001", "MIO002"]


MEETINGS = b"""<?xml version="1.0" encoding="ISO-8859-1" standalone="yes"?>
<nite:root nite:id="meet.00" xmlns:nite="http://nite.sourceforge.net/">
   <meeting nite:id="m1" observation="X" duration="1490">
      <speaker nite:id="X_1" channel="2" nxt_agent="A" global_name="FEE005"/>
      <speaker nite:id="X_2" channel="0" nxt_agent="B" global_name="MIO012"/>
   </meeting>
</nite:root>
"""

PARTICIPANTS = b"""<?xml version="1.0" encoding="ISO-8859-1" standalone="yes"?>
<nite:root nite:id="participants.00" xmlns:nite="http://nite.sourceforge.net/">
   <participant nite:id="FEE005" sex="F" native_language="English" meeting="X">
      <english_language nite:id="p1" region="Northen Ireland"/>
   </participant>
   <participant nite:id="MIO012" sex="M" native_language="Greek" meeting="X">
      <english_language nite:id="p2" country="England" months="12"/>
   </participant>
</nite:root>
"""

OTHER_WORDS = b"""<?xml version="1.0" encoding="ISO-8859-1" standalone="yes"?>
<nite:root nite:id="X.B.words" xmlns:nite="http://nite.sourceforge.net/">
   <w nite:id="X.B.words0" starttime="5.0" endtime="6.0">right</w>
</nite:root>
"""


def annotation_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("corpusResources/meetings.xml", MEETINGS)
        archive.writestr("corpusResources/participants.xml", PARTICIPANTS)
        archive.writestr("words/X.A.words.xml", WORDS)
        archive.writestr("words/X.B.words.xml", OTHER_WORDS)
        archive.writestr("disfluency/X.A.disfluency.xml", DISFLUENCY)
        archive.writestr("words/Y.A.words.xml", WORDS)  # no disfluency layer: skipped
    return buffer.getvalue()


def test_tracks_come_only_from_channels_with_a_disfluency_layer() -> None:
    with zipfile.ZipFile(io.BytesIO(annotation_zip())) as archive:
        tracks = tracks_from_zip(archive)
    assert [(t.meeting, t.agent, t.speaker, t.channel) for t in tracks] == [("X", "A", "FEE005", 2)]
    assert len(tracks[0].marks) == 4  # three hesitation-word or tagged marks plus "uh"
    assert tracks[0].others == [(5.0, 6.0)]  # agent B's speech is crosstalk for A


def test_speakers_record_first_language_and_region() -> None:
    with zipfile.ZipFile(io.BytesIO(annotation_zip())) as archive:
        people = speakers(archive)
    assert people["FEE005"] == {
        "sex": "F",
        "first_language": "English",
        "region": "Northen Ireland",
    }
    assert people["MIO012"] == {"sex": "M", "first_language": "Greek", "region": "England"}


def test_crosstalk_under_one_percent_of_the_window_counts_as_none() -> None:
    # 0.3 s of another speaker in 75 s is noise: own speech decides between these two.
    best = best_window(track(others=((0.0, 60.0), (140.0, 140.3))))
    assert best is not None
    assert best.crosstalk == 0.0
    chosen = choose_windows(
        [window("FEE001", 0.0, own=0.9), window("MEE002", 0.004, own=0.95)], count=1
    )
    assert chosen[0].speaker == "MEE002"


def header(channels: int = 1, rate: int = 16000, bits: int = 16, data: bytes = b"data") -> bytes:
    fmt = struct.pack(
        "<HHIIHH", 1, channels, rate, rate * channels * bits // 8, channels * bits // 8, bits
    )
    return (
        b"RIFF"
        + struct.pack("<I", 1000)
        + b"WAVE"
        + b"fmt "
        + struct.pack("<I", 16)
        + fmt
        + data
        + struct.pack("<I", 960)
    )


def test_pcm_byte_range_of_a_window_skips_the_44_byte_header() -> None:
    # 16 kHz, 16-bit mono is 32,000 bytes a second; the range is inclusive.
    assert pcm_byte_range(1.5, 75.0) == (44 + 48_000, 44 + 48_000 + 2_400_000 - 1)


def test_check_wav_header_accepts_ami_headset_format() -> None:
    check_wav_header(header())


@pytest.mark.parametrize(
    "bad", [header(channels=2), header(rate=44100), header(bits=24), header(data=b"LIST")]
)
def test_check_wav_header_refuses_any_other_layout(bad: bytes) -> None:
    with pytest.raises(ValueError):
        check_wav_header(bad)


PCM = bytes(range(256)) * 10  # 2,560 bytes = 0.08 s


def entry(pcm: bytes = PCM, speaker: str = "FEE005") -> dict:
    return {
        "name": f"ES2002a-{speaker}",
        "speaker": speaker,
        "audio_url": "https://groups.inf.ed.ac.uk/ami/AMICorpusMirror/amicorpus/ES2002a/audio/ES2002a.Headset-1.wav",
        "start": 2.0,
        "length": 0.08,
        "pcm_sha256": hashlib.sha256(pcm).hexdigest(),
        "marks": [
            {"start": i / 100, "end": i / 100 + 0.01, "kind": "hesitation", "text": "um"}
            for i in range(5)
        ],
    }


class FakeServer:
    def __init__(self, body: bytes = PCM) -> None:
        self.body = body
        self.calls: list[tuple[int, int]] = []

    def __call__(self, url: str, first: int, last: int) -> bytes:
        self.calls.append((first, last))
        return header() if first == 0 else self.body


def test_fetch_window_writes_wav_count_and_timed_marks(tmp_path: Path) -> None:
    server = FakeServer()
    wav_path = fetch_window(entry(), tmp_path, get=server)
    assert server.calls == [(0, 43), (44 + 64_000, 44 + 64_000 + 2_560 - 1)]
    with wave.open(str(wav_path)) as audio:
        assert (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) == (1, 2, 16000)
        assert audio.readframes(audio.getnframes()) == PCM
    assert (tmp_path / "ES2002a-FEE005.fillers").read_text() == "5\n"
    assert json.loads((tmp_path / "ES2002a-FEE005.marks.json").read_text()) == entry()["marks"]


def test_fetch_window_refuses_audio_that_does_not_match_the_manifest(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="checksum"):
        fetch_window(entry(), tmp_path, get=FakeServer(body=PCM[:-2] + b"xx"))
    assert list(tmp_path.iterdir()) == []


def test_fetch_window_refuses_a_short_range(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="bytes"):
        fetch_window(entry(), tmp_path, get=FakeServer(body=PCM[:100]))
    assert list(tmp_path.iterdir()) == []


def test_manifest_entry_names_the_headset_file_and_the_speaker() -> None:
    marks = tuple(FillerMark(float(i), i + 0.3, "hesitation", "uh") for i in range(5))
    chosen = Window("ES2002a", "B", "FEE005", 1, 12.5, 75.0, 0.9, 0.0, marks)
    people = {"FEE005": {"sex": "F", "first_language": "English", "region": "Northen Ireland"}}
    item = manifest_entry(chosen, people, "ab" * 32)
    assert item["audio_url"] == (
        "https://groups.inf.ed.ac.uk/ami/AMICorpusMirror/amicorpus/ES2002a/audio/ES2002a.Headset-1.wav"
    )
    assert (item["name"], item["speaker"], item["region"], item["start"]) == (
        "ES2002a-FEE005",
        "FEE005",
        "Northen Ireland",
        12.5,
    )
    assert item["marks"][0] == {"start": 0.0, "end": 0.3, "kind": "hesitation", "text": "uh"}
    validate_manifest({"windows": [item]}, count=1)


def test_validate_manifest_refuses_a_repeated_speaker_or_a_mark_outside_the_window() -> None:
    marks = [{"start": 1.0, "end": 1.2, "kind": "hesitation", "text": "um"}] * 5
    item = {
        "name": "M-FEE001",
        "speaker": "FEE001",
        "length": 75.0,
        "pcm_sha256": "0" * 64,
        "audio_url": "https://groups.inf.ed.ac.uk/x.wav",
        "start": 0.0,
        "marks": marks,
    }
    with pytest.raises(ValueError, match="speaker"):
        validate_manifest({"windows": [item, item]}, count=2)
    late = {**item, "marks": [*marks[:4], {**marks[0], "end": 75.5}]}
    with pytest.raises(ValueError, match="outside"):
        validate_manifest({"windows": [late]}, count=1)
    with pytest.raises(ValueError, match="windows"):
        validate_manifest({"windows": [item]}, count=20)


def test_range_get_uses_curl_as_is_and_fails_on_http_errors() -> None:
    seen: list[list[str]] = []

    def run(command: list[str]) -> bytes:
        seen.append(command)
        return b"x" * 44

    assert range_get("https://groups.inf.ed.ac.uk/a.wav", 0, 43, run=run) == b"x" * 44
    assert seen == [
        [
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--proto",
            "=https",
            "--max-time",
            "300",
            # A server that ignored the range would send the whole WAV: curl stops first.
            "--max-filesize",
            "44",
            "--range",
            "0-43",
            "https://groups.inf.ed.ac.uk/a.wav",
        ]
    ]


def test_fetch_all_pauses_between_requests_to_the_corpus_host(tmp_path: Path) -> None:
    server, pauses = FakeServer(), []
    second = entry(speaker="MEE006")
    paths = fetch_all(
        {"windows": [entry(), second]},
        tmp_path,
        get=server,
        sleep=pauses.append,
        count=2,
        length=0.08,
    )
    assert [p.name for p in paths] == ["ES2002a-FEE005.wav", "ES2002a-MEE006.wav"]
    assert len(server.calls) == 4 and pauses == [2.0, 2.0, 2.0]  # one pause between requests


def test_best_window_puts_no_crosstalk_before_more_own_speech() -> None:
    base = track()
    # The speaker talks more while the other speaker is also talking (before 70 s).
    words = [
        Word(w.id, w.start, w.start + (0.95 if w.start < 70 else 0.8), w.text) for w in base.words
    ]
    busier = Track(
        base.meeting, base.agent, base.speaker, base.channel, words, base.marks, base.others, 200.0
    )
    window = best_window(busier)
    assert window is not None and (window.start, window.crosstalk) == (66.0, 0.0)


def test_fetch_annotations_keeps_the_zip_only_when_its_checksum_matches(tmp_path: Path) -> None:
    def download(body: bytes):
        def run(command: list[str]) -> bytes:
            assert command[-1].endswith("/ami_public_manual_1.6.2.zip")
            return body

        return run

    good = b"zip bytes"
    path = fetch_annotations(
        tmp_path / "ami.zip", run=download(good), expected=hashlib.sha256(good).hexdigest()
    )
    assert path.read_bytes() == good
    with pytest.raises(ValueError, match="checksum"):
        fetch_annotations(
            tmp_path / "bad.zip", run=download(b"changed"), expected=ANNOTATIONS_SHA256
        )
    assert not (tmp_path / "bad.zip").exists()


def test_validate_manifest_refuses_a_wrong_length_a_negative_start_or_an_unsafe_name() -> None:
    marks = [{"start": 1.0, "end": 1.2, "kind": "hesitation", "text": "um"}] * 5
    item = {
        "name": "M-FEE001",
        "speaker": "FEE001",
        "length": 75.0,
        "pcm_sha256": "0" * 64,
        "audio_url": "https://groups.inf.ed.ac.uk/x.wav",
        "start": 0.0,
        "marks": marks,
    }
    validate_manifest({"windows": [item]}, count=1)
    for bad, message in (
        ({"length": 60.0}, "length"),
        ({"start": -1.0}, "start"),
        ({"name": "../M-FEE001"}, "name"),
    ):
        with pytest.raises(ValueError, match=message):
            validate_manifest({"windows": [{**item, **bad}]}, count=1)


def test_fetch_window_reuses_a_cached_window_only_when_its_audio_matches(tmp_path: Path) -> None:
    fetch_window(entry(), tmp_path, get=FakeServer())
    unused = FakeServer()
    fetch_window(entry(), tmp_path, get=unused)
    assert unused.calls == []  # restored from the workflow cache: no request to the host
    wav = tmp_path / "ES2002a-FEE005.wav"
    damaged = bytearray(wav.read_bytes())
    damaged[-1] ^= 0xFF  # one changed sample: the cached copy must not be trusted
    wav.write_bytes(bytes(damaged))
    again = FakeServer()
    fetch_window(entry(), tmp_path, get=again)
    assert len(again.calls) == 2
