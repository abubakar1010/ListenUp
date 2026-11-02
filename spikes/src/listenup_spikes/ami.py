"""AMI Meeting Corpus (CC BY 4.0) as B4's filler reference (#22, exception E4).

AMI's manual annotations tag hesitations and discourse markers on time-stamped words
(NXT XML). B4 counts only its own fillers: hesitations spelled uh, um, er or erm, and
discourse-marker "like" and "you know". AMI spells every pure-vowel hesitation "uh".
Licence: https://groups.inf.ed.ac.uk/ami/corpus/license.shtml (attribution required).
"""

import argparse
import hashlib
import json
import re
import struct
import subprocess
import time
import xml.etree.ElementTree as ET
import zipfile
from bisect import bisect_left
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from listenup_spikes.metrics import FillerMark

NITE = "{http://nite.sourceforge.net/}"
HESITATION_TYPE = "ami_dsfl_5"
DISCOURSE_TYPE = "ami_dsfl_3"
HESITATION_WORDS = frozenset({"uh", "um", "er", "erm"})
_CHILD = re.compile(r"id\(([^)]+)\)(?:\.\.id\(([^)]+)\))?")


@dataclass(frozen=True)
class Word:
    id: str
    start: float
    end: float
    text: str


def parse_words(xml: bytes) -> list[Word]:
    """The timed, non-punctuation words of one AMI words file, in file order."""
    words = []
    for element in ET.fromstring(xml):
        if element.tag != "w" or element.get("punc"):
            continue
        try:
            start, end = float(element.get("starttime", "")), float(element.get("endtime", ""))
        except ValueError:
            continue  # untimed words cannot be matched against a transcript
        words.append(Word(element.get(f"{NITE}id", ""), start, end, (element.text or "").lower()))
    return words


def _spans(disfluency_xml: bytes) -> list[tuple[str, list[tuple[str, str | None]]]]:
    spans = []
    for dsfl in ET.fromstring(disfluency_xml):
        kind = ""
        children: list[tuple[str, str | None]] = []
        for part in dsfl:
            href = part.get("href", "")
            if part.get("role") == "dsfl-type":
                kind = href.rsplit("(", 1)[-1].rstrip(")")
            elif part.tag == f"{NITE}child" and (match := _CHILD.search(href)):
                children.append((match.group(1), match.group(2)))
        spans.append((kind, children))
    return spans


def filler_marks(words: list[Word], disfluency_xml: bytes) -> list[FillerMark]:
    """B4 fillers the annotators tagged, sorted by start time."""
    index = {word.id: i for i, word in enumerate(words)}
    marks = []
    for kind, children in _spans(disfluency_xml):
        if kind not in (HESITATION_TYPE, DISCOURSE_TYPE):
            continue
        for first, last in children:
            if first not in index or (last is not None and last not in index):
                continue  # the span starts or ends on an untimed word
            span = words[index[first] : index[last or first] + 1]
            marks += _hesitations(span) if kind == HESITATION_TYPE else _discourse(span)
    return sorted(marks, key=lambda m: (m.start, m.end))


def _hesitations(span: list[Word]) -> list[FillerMark]:
    return [
        FillerMark(w.start, w.end, "hesitation", w.text) for w in span if w.text in HESITATION_WORDS
    ]


def _discourse(span: list[Word]) -> list[FillerMark]:
    marks = []
    i = 0
    while i < len(span):
        word = span[i]
        if word.text == "you" and i + 1 < len(span) and span[i + 1].text == "know":
            marks.append(FillerMark(word.start, span[i + 1].end, "discourse", "you know"))
            i += 2
            continue
        if word.text == "like":
            marks.append(FillerMark(word.start, word.end, "discourse", "like"))
        i += 1
    return marks


WINDOW_S = 75.0  # the Shadow recording length the filler pass runs on (#22)
MIN_OWN_SPEECH = 0.6
MIN_FILLERS = 5
MAX_DUTCH = 4  # TNO speakers (third ID letter "D") would otherwise fill the list
# Crosstalk is compared in steps of 1% of the window (0.75 s): less is noise, and own
# speech then decides.
CROSSTALK_STEP = 2  # decimal places


@dataclass(frozen=True)
class Track:
    """One speaker's headset channel in one meeting, with everyone else's speech."""

    meeting: str
    agent: str
    speaker: str
    channel: int
    words: list[Word]
    marks: list[FillerMark]
    others: list[tuple[float, float]]


@dataclass(frozen=True)
class Window:
    meeting: str
    agent: str
    speaker: str
    channel: int
    start: float
    length: float
    own: float  # share of the window the speaker is talking
    crosstalk: float  # other speakers' talk in the window, as a share of its length
    marks: tuple[FillerMark, ...]  # times relative to the window start

    @property
    def name(self) -> str:
        return f"{self.meeting}-{self.speaker}"


class _Spans:
    """Sorted intervals with a fast overlap sum for a window (word spans are short)."""

    def __init__(self, spans: list[tuple[float, float]]) -> None:
        self.spans = sorted(spans)
        self.starts = [s for s, _ in self.spans]
        self.longest = max((e - s for s, e in self.spans), default=0.0)

    def overlap(self, start: float, end: float) -> float:
        lo = bisect_left(self.starts, start - self.longest)
        hi = bisect_left(self.starts, end)
        return sum(max(0.0, min(e, end) - max(s, start)) for s, e in self.spans[lo:hi])


def best_window(track: Track, length: float = WINDOW_S) -> Window | None:
    """The speaker's window with the least crosstalk, then the most own speech, then the
    earliest start, among windows that start at a word onset, where the speaker talks at
    least 60% of the time and at least five B4 fillers fall wholly inside. Filler counts
    are a floor, never maximised, so the selection does not favour easy recordings."""
    own_spans = _Spans([(w.start, w.end) for w in track.words])
    other_spans = _Spans(track.others)
    marks = sorted(track.marks, key=lambda m: m.start)
    mark_starts = [m.start for m in marks]
    best: tuple[tuple[float, float, float], Window] | None = None
    for word in track.words:
        start, end = word.start, word.start + length
        lo, hi = bisect_left(mark_starts, start), bisect_left(mark_starts, end)
        inside = [m for m in marks[lo:hi] if m.end <= end]
        if len(inside) < MIN_FILLERS:
            continue
        own = round(own_spans.overlap(start, end) / length, 3)
        if own < MIN_OWN_SPEECH:
            continue
        crosstalk = round(other_spans.overlap(start, end) / length, CROSSTALK_STEP)
        key = (crosstalk, -own, start)
        if best is None or key < best[0]:
            relative = tuple(
                FillerMark(round(m.start - start, 3), round(m.end - start, 3), m.kind, m.text)
                for m in inside
            )
            window = Window(
                track.meeting,
                track.agent,
                track.speaker,
                track.channel,
                start,
                length,
                own,
                crosstalk,
                relative,
            )
            best = (key, window)
    return best[1] if best else None


def choose_windows(windows: list[Window], count: int = 20) -> list[Window]:
    """One window per speaker, least crosstalk first, at most four TNO (Dutch) speakers."""
    chosen: list[Window] = []
    seen: set[str] = set()
    dutch = 0
    for window in sorted(
        windows, key=lambda w: (round(w.crosstalk, CROSSTALK_STEP), -w.own, w.speaker, w.start)
    ):
        if window.speaker in seen:
            continue
        is_dutch = window.speaker[2:3] == "D"
        if is_dutch and dutch >= MAX_DUTCH:
            continue
        seen.add(window.speaker)
        dutch += is_dutch
        chosen.append(window)
        if len(chosen) == count:
            break
    return chosen


def _channels(archive: zipfile.ZipFile) -> dict[tuple[str, str], tuple[str, int]]:
    """(meeting, agent) -> (speaker id, headset channel), from corpusResources/meetings.xml."""
    out = {}
    for meeting in ET.fromstring(archive.read("corpusResources/meetings.xml")):
        for speaker in meeting:
            key = (meeting.get("observation", ""), speaker.get("nxt_agent", ""))
            out[key] = (speaker.get("global_name", ""), int(speaker.get("channel", "-1")))
    return out


def speakers(archive: zipfile.ZipFile) -> dict[str, dict[str, str]]:
    """Speaker id -> sex, first language and the region or country of their English."""
    out = {}
    for person in ET.fromstring(archive.read("corpusResources/participants.xml")):
        english = person.find("english_language")
        region = ""
        if english is not None:
            region = english.get("region") or english.get("country") or ""
        out[person.get(f"{NITE}id", "")] = {
            "sex": person.get("sex", ""),
            "first_language": person.get("native_language", ""),
            "region": region,
        }
    return out


def tracks_from_zip(archive: zipfile.ZipFile) -> list[Track]:
    """A track per channel that has the manual disfluency layer (40 meetings in 1.6.2)."""
    names = set(archive.namelist())
    channels = _channels(archive)
    by_meeting: dict[str, dict[str, list[Word]]] = {}
    for name in sorted(names):
        path = PurePosixPath(name)
        if path.parent.name == "words" and path.name.endswith(".words.xml"):
            meeting, agent = path.name.split(".")[:2]
            by_meeting.setdefault(meeting, {})[agent] = parse_words(archive.read(name))
    tracks = []
    for meeting, agents in sorted(by_meeting.items()):
        for agent, words in sorted(agents.items()):
            layer = f"disfluency/{meeting}.{agent}.disfluency.xml"
            if layer not in names or (meeting, agent) not in channels:
                continue
            speaker, channel = channels[(meeting, agent)]
            others = sorted((w.start, w.end) for a, ws in agents.items() if a != agent for w in ws)
            marks = filler_marks(words, archive.read(layer))
            tracks.append(Track(meeting, agent, speaker, channel, words, marks, others))
    return tracks


# AMI headset WAVs are PCM, 16 kHz, mono, 16-bit, with the data chunk right after a 44-byte
# header; check_wav_header refuses anything else rather than guessing offsets.
RATE = 16000
SAMPLE_BYTES = 2
HEADER_BYTES = 44

RangeGet = Callable[[str, int, int], bytes]


def pcm_byte_range(start: float, length: float) -> tuple[int, int]:
    """Inclusive byte range of a window's samples in an AMI headset WAV."""
    first = HEADER_BYTES + round(start * RATE) * SAMPLE_BYTES
    return first, first + round(length * RATE) * SAMPLE_BYTES - 1


def check_wav_header(header: bytes) -> None:
    if len(header) < HEADER_BYTES or header[:4] != b"RIFF" or header[8:16] != b"WAVEfmt ":
        raise ValueError("not a RIFF/WAVE file with fmt first")
    fmt, channels, rate, _, _, bits = struct.unpack("<HHIIHH", header[20:36])
    if (fmt, channels, rate, bits) != (1, 1, RATE, SAMPLE_BYTES * 8):
        raise ValueError(f"expected PCM 16 kHz mono 16-bit, got {fmt=} {channels=} {rate=} {bits=}")
    if header[36:40] != b"data":
        raise ValueError("the data chunk does not follow the 44-byte header")


def wav_file(pcm: bytes) -> bytes:
    fmt = struct.pack("<HHIIHH", 1, 1, RATE, RATE * SAMPLE_BYTES, SAMPLE_BYTES, SAMPLE_BYTES * 8)
    return (
        b"RIFF"
        + struct.pack("<I", 36 + len(pcm))
        + b"WAVE"
        + b"fmt "
        + struct.pack("<I", 16)
        + fmt
        + b"data"
        + struct.pack("<I", len(pcm))
        + pcm
    )


def _curl(command: list[str]) -> bytes:
    return subprocess.run(command, check=True, capture_output=True).stdout


def range_get(url: str, first: int, last: int, run: Callable[[list[str]], bytes] = _curl) -> bytes:
    """One HTTP range request with curl, the kind of command-line download AMI's own
    download page points to (its host refuses Python's urllib). curl keeps its own
    identity and the inherited proxy and TLS settings: no retries, alternate hosts or
    disabled verification, and an HTTP error stops the run."""
    return run(
        [
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--proto",
            "=https",
            "--max-time",
            "300",
            "--range",
            f"{first}-{last}",
            url,
        ]
    )


PAUSE_S = 2.0  # between requests: 40 small requests a run, spaced out for a university host


def paced(get: RangeGet, sleep: Callable[[float], None] = time.sleep) -> RangeGet:
    """The same requests, one at a time with a pause before every request but the first."""
    calls = 0

    def wrapped(url: str, first: int, last: int) -> bytes:
        nonlocal calls
        if calls:
            sleep(PAUSE_S)
        calls += 1
        return get(url, first, last)

    return wrapped


def window_pcm(url: str, start: float, length: float, get: RangeGet = range_get) -> bytes:
    """A window's samples, after checking the file's format and the range's length (a
    server that ignored the range would send the whole file)."""
    check_wav_header(get(url, 0, HEADER_BYTES - 1))
    first, last = pcm_byte_range(start, length)
    pcm = get(url, first, last)
    if len(pcm) != last - first + 1:
        raise ValueError(f"{url}: got {len(pcm)} bytes, expected {last - first + 1}")
    return pcm


def fetch_window(entry: dict, out_dir: Path, get: RangeGet = range_get) -> Path:
    """Write NAME.wav, NAME.fillers (the count spike-b4 reads) and NAME.marks.json (timed
    marks for matching), after checking the format and the manifest's SHA-256."""
    pcm = window_pcm(entry["audio_url"], entry["start"], entry["length"], get)
    if hashlib.sha256(pcm).hexdigest() != entry["pcm_sha256"]:
        raise ValueError(f"{entry['name']}: audio checksum does not match the manifest")
    out_dir.mkdir(parents=True, exist_ok=True)
    wav_path = out_dir / f"{entry['name']}.wav"
    wav_path.write_bytes(wav_file(pcm))
    (out_dir / f"{entry['name']}.fillers").write_text(f"{len(entry['marks'])}\n")
    (out_dir / f"{entry['name']}.marks.json").write_text(json.dumps(entry["marks"], indent=1))
    return wav_path


AUDIO_URL = "https://groups.inf.ed.ac.uk/ami/AMICorpusMirror/amicorpus/{meeting}/audio/{meeting}.Headset-{channel}.wav"
ANNOTATIONS_URL = "https://groups.inf.ed.ac.uk/ami/AMICorpusAnnotations/ami_public_manual_1.6.2.zip"
# SHA-256 of the 22,887,865-byte zip downloaded on 2026-11-01 for the #22 corpus research.
ANNOTATIONS_SHA256 = "b56e5babb2496b8795deeeda7e71178d7fbc9963f94276cf2a3f4b56ebbc9f9d"
MANIFEST = Path(__file__).resolve().parents[2] / "b4" / "ami-windows.json"
WINDOW_COUNT = 20


def manifest_entry(window: Window, people: dict[str, dict[str, str]], pcm_sha256: str) -> dict:
    person = people.get(window.speaker, {})
    return {
        "name": window.name,
        "meeting": window.meeting,
        "agent": window.agent,
        "speaker": window.speaker,
        "sex": person.get("sex", window.speaker[:1]),
        # TNO speakers have no participants.xml record; their ID marks them Dutch.
        "first_language": person.get("first_language")
        or ("Dutch" if window.speaker[2:3] == "D" else ""),
        "region": person.get("region", ""),
        "channel": window.channel,
        "audio_url": AUDIO_URL.format(meeting=window.meeting, channel=window.channel),
        "start": window.start,
        "length": window.length,
        "own_speech": window.own,
        "crosstalk": window.crosstalk,
        "pcm_sha256": pcm_sha256,
        "marks": [
            {"start": m.start, "end": m.end, "kind": m.kind, "text": m.text} for m in window.marks
        ],
    }


def validate_manifest(manifest: dict, count: int = WINDOW_COUNT) -> None:
    windows = manifest.get("windows", [])
    if len(windows) != count:
        raise ValueError(f"expected {count} windows, found {len(windows)}")
    speakers_seen = [w["speaker"] for w in windows]
    if len(set(speakers_seen)) != len(speakers_seen):
        raise ValueError("a speaker appears in more than one window")
    for w in windows:
        if not w["audio_url"].startswith("https://groups.inf.ed.ac.uk/"):
            raise ValueError(f"{w['name']}: audio must come from the AMI host")
        if len(w["pcm_sha256"]) != 64:
            raise ValueError(f"{w['name']}: missing SHA-256")
        if len(w["marks"]) < MIN_FILLERS:
            raise ValueError(f"{w['name']}: fewer than {MIN_FILLERS} fillers")
        if any(m["start"] < 0 or m["end"] > w["length"] for m in w["marks"]):
            raise ValueError(f"{w['name']}: a mark falls outside the window")


def fetch_all(
    manifest: dict,
    out_dir: Path,
    get: RangeGet = range_get,
    sleep: Callable[[float], None] = time.sleep,
    count: int = WINDOW_COUNT,
) -> list[Path]:
    validate_manifest(manifest, count=count)
    polite = paced(get, sleep)
    return [fetch_window(entry, out_dir, polite) for entry in manifest["windows"]]


def fetch_annotations(
    dest: Path, run: Callable[[list[str]], bytes] = _curl, expected: str = ANNOTATIONS_SHA256
) -> Path:
    """Download AMI's manual annotations (text only) and keep them only if unchanged."""
    body = run(
        [
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--proto",
            "=https",
            "--max-time",
            "600",
            ANNOTATIONS_URL,
        ]
    )
    if hashlib.sha256(body).hexdigest() != expected:
        raise ValueError(f"{ANNOTATIONS_URL}: checksum does not match the pinned SHA-256")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    return dest


def build_manifest(annotations: Path, get: RangeGet = range_get) -> dict:
    """Choose the windows from the annotation zip and pin each window's audio checksum."""
    get = paced(get)
    with zipfile.ZipFile(annotations) as archive:
        tracks = tracks_from_zip(archive)
        people = speakers(archive)
    windows = choose_windows([w for t in tracks if (w := best_window(t))])
    entries = []
    for window in windows:
        url = AUDIO_URL.format(meeting=window.meeting, channel=window.channel)
        digest = hashlib.sha256(window_pcm(url, window.start, window.length, get)).hexdigest()
        entries.append(manifest_entry(window, people, digest))
    manifest = {
        "source": {
            "corpus": "AMI Meeting Corpus",
            "licence": "CC BY 4.0",
            "licence_url": "https://groups.inf.ed.ac.uk/ami/corpus/license.shtml",
            "attribution": "AMI Consortium, AMI Meeting Corpus. Excerpts of 75 s from the "
            "headset audio and their manual word and disfluency annotations.",
            "annotations_url": ANNOTATIONS_URL,
            "annotations_sha256": hashlib.sha256(annotations.read_bytes()).hexdigest(),
        },
        "rule": {
            "window_s": WINDOW_S,
            "min_own_speech": MIN_OWN_SPEECH,
            "min_fillers": MIN_FILLERS,
            "crosstalk_step": 10**-CROSSTALK_STEP,
            "max_dutch": MAX_DUTCH,
            "order": "crosstalk, then own speech (more first), then earliest start",
            "fillers": "hesitations uh, um, er, erm; discourse markers like, you know",
        },
        "windows": entries,
    }
    validate_manifest(manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="AMI windows for B4 (#22)")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("manifest", help="choose windows and pin checksums")
    build.add_argument(
        "annotations", type=Path, help="ami_public_manual_1.6.2.zip (downloaded if missing)"
    )
    build.add_argument("--out", type=Path, default=MANIFEST)
    fetch = commands.add_parser("fetch", help="download the windows named in the manifest")
    fetch.add_argument("out", type=Path)
    fetch.add_argument("--manifest", type=Path, default=MANIFEST)
    args = parser.parse_args()

    if args.command == "manifest":
        if not args.annotations.exists():
            fetch_annotations(args.annotations)
        manifest = build_manifest(args.annotations)
        args.out.write_text(json.dumps(manifest, indent=1) + "\n")
        print(f"wrote {args.out}: {len(manifest['windows'])} windows")
        return
    if not args.manifest.exists():
        raise SystemExit(
            f"{args.manifest} is missing: run the speech-benchmarks workflow with "
            "b4-ami-manifest and commit its ami-windows.json there"
        )
    for path in fetch_all(json.loads(args.manifest.read_text()), args.out):
        print(f"fetched {path}", flush=True)
