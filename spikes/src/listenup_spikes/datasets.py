"""Build B1/B2 test passages from licence-safe corpora.

Usage:
    spike-passages librispeech data/raw/LibriSpeech/test-clean data/passages --count 8
    spike-passages voxpopuli data/raw/vp_en_test.parquet data/passages --set vp-en --count 3

Sources:
- LibriSpeech test-clean and test-other (openslr.org/12): LibriVox public-domain audio
  with human-verified text (CC BY 4.0). Each passage joins one chapter's utterances in
  order until it reaches the target length.
- VoxPopuli `en` and `en_accented` test sets (CC0, Hugging Face facebook/voxpopuli):
  European Parliament speeches. No single speech in the test sets runs 3 minutes, so a
  passage joins whole consecutive speeches of one debate (agenda item); the gaps between
  segments are removed, as in LibriSpeech.

Each passage is written as NAME.wav (16 kHz mono), NAME.txt (the passage's reference
text) and NAME.json (where the passage sits in the file, the segment times and the
source). As in the product (System Design 5.1), the file holds the passage plus 5 s of
real neighbouring speech on each side; the harness trims results to the passage.
"""

import argparse
import io
import json
import re
from collections import defaultdict
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000
PAD_S = 5.0


@dataclass(frozen=True)
class Utterance:
    id: str
    text: str
    audio: np.ndarray  # float32 mono at SAMPLE_RATE

    @property
    def seconds(self) -> float:
        return len(self.audio) / SAMPLE_RATE


def choose_span(
    durations: Sequence[float], target_s: float, pad_s: float = PAD_S
) -> tuple[int, int] | None:
    """First run [first, last) of utterances lasting at least target_s, with at least
    pad_s of audio before it and after it. None when the sequence is too short."""
    before = 0.0
    for first in range(len(durations)):
        if before >= pad_s:
            total = 0.0
            for last in range(first, len(durations)):
                total += durations[last]
                if total >= target_s:
                    if sum(durations[last + 1 :]) >= pad_s:
                        return first, last + 1
                    return None
            return None
        before += durations[first]
    return None


def assemble(
    utterances: Sequence[Utterance], first: int, last: int, pad_s: float = PAD_S
) -> tuple[np.ndarray, dict[str, object]]:
    """The passage utterances[first:last] with pad_s of neighbouring audio on each side.

    Returns the audio and the layout: pad_before_s, passage_s and each passage
    segment's start and end in the file."""
    pad = round(pad_s * SAMPLE_RATE)
    before = np.concatenate([u.audio for u in utterances[:first]])[-pad:]
    after = np.concatenate([u.audio for u in utterances[last:]])[:pad]
    segments, cursor = [], len(before)
    for u in utterances[first:last]:
        segments.append(
            {
                "id": u.id,
                "start": round(cursor / SAMPLE_RATE, 3),
                "end": round((cursor + len(u.audio)) / SAMPLE_RATE, 3),
                "text": u.text,
            }
        )
        cursor += len(u.audio)
    audio = np.concatenate([before, *(u.audio for u in utterances[first:last]), after])
    layout: dict[str, object] = {
        "pad_before_s": round(len(before) / SAMPLE_RATE, 3),
        "passage_s": round((cursor - len(before)) / SAMPLE_RATE, 3),
        "pad_after_s": round(len(after) / SAMPLE_RATE, 3),
        "segments": segments,
    }
    return audio.astype(np.float32), layout


def write_passage(
    out: Path, name: str, audio: np.ndarray, layout: dict[str, object], meta: dict[str, object]
) -> None:
    import soundfile as sf

    out.mkdir(parents=True, exist_ok=True)
    sf.write(out / f"{name}.wav", audio, SAMPLE_RATE, subtype="PCM_16")
    segments = layout["segments"]
    assert isinstance(segments, list)
    (out / f"{name}.txt").write_text(" ".join(s["text"] for s in segments) + "\n")
    (out / f"{name}.json").write_text(json.dumps({"name": name, **meta, **layout}, indent=1))


def _read_audio(data: bytes | Path) -> np.ndarray:
    import soundfile as sf

    audio, rate = sf.read(io.BytesIO(data) if isinstance(data, bytes) else data, dtype="float32")
    if rate != SAMPLE_RATE or audio.ndim != 1:
        raise ValueError(f"expected 16 kHz mono, got {rate} Hz, shape {audio.shape}")
    return audio


# LibriSpeech -------------------------------------------------------------------------


def librispeech_speakers(root: Path) -> dict[str, str]:
    """Speaker id to sex (F or M) from SPEAKERS.TXT next to the subset folder."""
    sexes = {}
    for line in (root.parent / "SPEAKERS.TXT").read_text().splitlines():
        if line.startswith(";"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 2:
            sexes[parts[0]] = parts[1]
    return sexes


def librispeech_chapter(chapter: Path) -> list[Utterance]:
    trans = next(chapter.glob("*.trans.txt"))
    items = []
    for line in trans.read_text().splitlines():
        utt_id, _, text = line.partition(" ")
        items.append(
            Utterance(utt_id, text.strip().lower(), _read_audio(chapter / f"{utt_id}.flac"))
        )
    return items


def alternate_by_sex(speakers: Sequence[str], sexes: dict[str, str]) -> list[str]:
    """Speakers ordered F, M, F, M... (each group in id order), so any prefix is balanced."""
    women = sorted((s for s in speakers if sexes.get(s) == "F"), key=int)
    men = sorted((s for s in speakers if sexes.get(s) != "F"), key=int)
    out = []
    for i in range(max(len(women), len(men))):
        out += women[i : i + 1] + men[i : i + 1]
    return out


def build_librispeech(root: Path, out: Path, count: int, seconds: float) -> int:
    subset = root.name
    sexes = librispeech_speakers(root)
    made = 0
    for speaker in alternate_by_sex([p.name for p in root.iterdir()], sexes):
        if made == count:
            break
        for chapter in sorted((root / speaker).iterdir()):  # one passage per speaker
            utterances = librispeech_chapter(chapter)
            span = choose_span([u.seconds for u in utterances], seconds)
            if span is None:
                continue
            audio, layout = assemble(utterances, *span)
            name = f"ls-{subset.removeprefix('test-')}-{speaker}-{chapter.name}"
            meta = {
                "set": subset,
                "source": f"LibriSpeech {subset}, speaker {speaker}, chapter {chapter.name}",
                "licence": "CC BY 4.0 (audio public domain, LibriVox)",
                "speaker_sex": sexes.get(speaker),
            }
            write_passage(out, name, audio, layout, meta)
            made += 1
            print(f"wrote {name} ({layout['passage_s']} s)")
            break
    return made


# VoxPopuli ---------------------------------------------------------------------------

_SEGMENT_ID = re.compile(r"^(?P<speech>(?P<debate>[^_]+)_[^_]+)_(?P<index>\d+)$")


def voxpopuli_debates(rows: Sequence[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    """Segments grouped by debate, ordered by speech start then segment index."""
    debates: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        m = _SEGMENT_ID.match(str(row["audio_id"]))
        if m:
            debates[m["debate"]].append({**row, "_speech": m["speech"], "_index": int(m["index"])})
    for segments in debates.values():
        segments.sort(key=lambda r: (str(r["_speech"]), int(str(r["_index"]))))
    return debates


def _voxpopuli_rows(
    parquets: Sequence[Path], columns: Sequence[str]
) -> Iterator[dict[str, object]]:
    import pyarrow.parquet as pq

    for path in parquets:
        for batch in pq.ParquetFile(path).iter_batches(batch_size=256, columns=list(columns)):
            yield from batch.to_pylist()


def build_voxpopuli(
    parquets: Sequence[Path], out: Path, set_name: str, count: int, seconds: float
) -> int:
    import soundfile as sf

    # Pass 1: text and durations only (the accented test set is about 5 GB of audio).
    rows = []
    for row in _voxpopuli_rows(parquets, ["audio_id", "audio", "raw_text", "speaker_id", "accent"]):
        audio = row.pop("audio")
        assert isinstance(audio, dict)
        rows.append({**row, "_seconds": sf.info(io.BytesIO(audio["bytes"])).duration})
    candidates = []
    for debate, segments in sorted(voxpopuli_debates(rows).items()):
        span = choose_span([float(str(s["_seconds"])) for s in segments], seconds)
        if span:
            accents = sorted({str(s["accent"]) for s in segments[span[0] : span[1]]})
            candidates.append((debate, segments, span, accents))
    # Prefer debates whose speakers have accents not used yet, then by name.
    chosen, used_accents = [], set()
    while candidates and len(chosen) < count:
        candidates.sort(key=lambda c: (bool(set(c[3]) & used_accents), c[0]))
        chosen.append(candidates.pop(0))
        used_accents |= set(chosen[-1][3])
    # Pass 2: audio of the chosen debates only.
    wanted = {str(s["audio_id"]) for _, segments, _, _ in chosen for s in segments}
    audio_of = {
        str(r["audio_id"]): _read_audio(r["audio"]["bytes"])  # type: ignore[index]
        for r in _voxpopuli_rows(parquets, ["audio_id", "audio"])
        if r["audio_id"] in wanted
    }
    for debate, segments, span, accents in chosen:
        utterances = [
            Utterance(str(s["audio_id"]), str(s["raw_text"]).strip(), audio_of[str(s["audio_id"])])
            for s in segments
        ]
        audio, layout = assemble(utterances, *span)
        name = f"{set_name}-{debate.lower()}"
        meta = {
            "set": set_name,
            "source": f"VoxPopuli {set_name} test, debate {debate}",
            "licence": "CC0 1.0",
            "speakers": sorted({str(s["speaker_id"]) for s in segments[span[0] : span[1]]}),
            "accents": accents,
        }
        write_passage(out, name, audio, layout, meta)
        print(f"wrote {name} ({layout['passage_s']} s, accents {accents})")
    return len(chosen)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="corpus", required=True)
    ls = sub.add_parser("librispeech")
    ls.add_argument("source", type=Path, help="LibriSpeech/test-clean or test-other")
    vp = sub.add_parser("voxpopuli")
    vp.add_argument("source", type=Path, nargs="+", help="VoxPopuli test parquet files")
    vp.add_argument("--set", required=True, help="set name, e.g. vp-en or vp-accented")
    for p in (ls, vp):
        p.add_argument("out", type=Path)
        p.add_argument("--count", type=int, default=8)
        p.add_argument("--seconds", type=float, default=180.0)
    args = parser.parse_args()
    if args.corpus == "librispeech":
        made = build_librispeech(args.source, args.out, args.count, args.seconds)
    else:
        made = build_voxpopuli(args.source, args.out, args.set, args.count, args.seconds)
    print(f"{made} passages in {args.out}")


if __name__ == "__main__":
    main()
