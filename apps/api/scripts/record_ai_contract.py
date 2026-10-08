"""Record a speech adapter's raw engine output for the contract tests (ADR 0028).

Run on a machine with the speech extra and the models (the worker-media image or the
stage 0 server), then commit the file under tests/contract/recordings/:

    uv run python scripts/record_ai_contract.py transcription clip.flac
    uv run python scripts/record_ai_contract.py alignment clip.flac --text "The quick brown fox"

The provider's model and options come from the packaged ai.yaml (not LISTENUP_AI_CONFIG),
so a recording shows what production runs; --model records another model with the same
options. A provider that ai.yaml does not configure for the role is refused.

CI replays the recording through the whole adapter without the model.
"""

import argparse
import json
from pathlib import Path

from listenup.ai.config import DEFAULT_CONFIG, ProviderEntry, load_config
from listenup.ai.ports import Role
from listenup.ai.providers import faster_whisper, wav2vec2_ctc

RECORDINGS = Path(__file__).resolve().parents[1] / "tests" / "contract" / "recordings"


def configured_entry(role: Role, provider: str, model: str | None) -> ProviderEntry:
    """The role's entry for `provider` in ai.yaml, with `model` instead if given."""
    for entry in load_config(DEFAULT_CONFIG).providers(role):
        if entry.provider == provider:
            return entry if model is None else entry.model_copy(update={"model": model})
    raise SystemExit(f"{DEFAULT_CONFIG} configures no {provider} provider for {role.value}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", choices=["transcription", "alignment"])
    parser.add_argument("audio", type=Path)
    parser.add_argument("--model", help="default: the model in ai.yaml")
    parser.add_argument("--text", help="reference text (alignment)")
    parser.add_argument("--name", help="recording name; default <provider>_<audio stem>")
    args = parser.parse_args()

    record: dict[str, object] = {"source": "recorded", "port": args.port}
    if args.port == "transcription":
        entry = configured_entry(Role.TRANSCRIPTION, faster_whisper.PROVIDER, args.model)
        whisper = faster_whisper.FasterWhisperEngine(entry)
        raw_t = whisper.run(args.audio, "en")
        record |= {
            "model": entry.model,
            "options": entry.options,
            "provider": faster_whisper.PROVIDER,
            "version": whisper.version,
            "input": {"audio": args.audio.name, "language": "en"},
            "raw": raw_t.model_dump(),
        }
    else:
        if not args.text:
            parser.error("alignment needs --text")
        entry = configured_entry(Role.ALIGNMENT, wav2vec2_ctc.PROVIDER, args.model)
        ctc = wav2vec2_ctc.TorchaudioCtcEngine(entry)
        words = [w.tokens for w in wav2vec2_ctc.alignable_words(args.text)]
        raw_a = ctc.run(args.audio, words)
        record |= {
            "model": entry.model,
            "options": entry.options,
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
