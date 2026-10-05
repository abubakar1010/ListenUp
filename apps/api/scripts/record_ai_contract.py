"""Record a speech adapter's raw engine output for the contract tests (ADR 0028).

Run on a machine with the speech extra and the models (the worker-media image or the
stage 0 server), then commit the file under tests/contract/recordings/:

    uv run python scripts/record_ai_contract.py transcription fox.wav --model base.en
    uv run python scripts/record_ai_contract.py alignment fox.wav --model MMS_FA \\
        --text "The quick brown fox"

CI replays the recording through the whole adapter without the model.
"""

import argparse
import json
from pathlib import Path

from listenup.ai.config import ProviderEntry
from listenup.ai.providers import faster_whisper, wav2vec2_ctc

RECORDINGS = Path(__file__).resolve().parents[1] / "tests" / "contract" / "recordings"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", choices=["transcription", "alignment"])
    parser.add_argument("audio", type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--text", help="reference text (alignment)")
    parser.add_argument("--name", help="recording name; default <provider>_<audio stem>")
    args = parser.parse_args()

    record: dict[str, object] = {"source": "recorded", "port": args.port, "model": args.model}
    if args.port == "transcription":
        entry = ProviderEntry(provider=faster_whisper.PROVIDER, model=args.model)
        whisper = faster_whisper.FasterWhisperEngine(entry)
        raw_t = whisper.run(args.audio, "en")
        record |= {
            "provider": faster_whisper.PROVIDER,
            "version": whisper.version,
            "input": {"audio": args.audio.name, "language": "en"},
            "raw": raw_t.model_dump(),
        }
    else:
        if not args.text:
            parser.error("alignment needs --text")
        entry = ProviderEntry(provider=wav2vec2_ctc.PROVIDER, model=args.model)
        ctc = wav2vec2_ctc.TorchaudioCtcEngine(entry)
        words = [w.tokens for w in wav2vec2_ctc.alignable_words(args.text)]
        raw_a = ctc.run(args.audio, words)
        record |= {
            "provider": wav2vec2_ctc.PROVIDER,
            "version": ctc.version,
            "input": {"audio": args.audio.name, "text": args.text},
            "raw": raw_a.model_dump(),
        }
    name = args.name or f"{str(record['provider']).replace('-', '_')}_{args.audio.stem}"
    out = RECORDINGS / f"{name}.json"
    out.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
