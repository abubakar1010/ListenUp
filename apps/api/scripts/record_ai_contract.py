"""Record a speech adapter's raw engine output for the contract tests (ADR 0028).

Run on a machine with the speech extra and the models (the worker-media image or the
stage 0 server), then commit the file under tests/contract/recordings/:

    uv run python scripts/record_ai_contract.py transcription clip.flac
    uv run python scripts/record_ai_contract.py alignment clip.flac --text "The quick brown fox"

The provider's model and options come from ai.yaml, so a recording shows what production
runs; --model records another model with the same options.

CI replays the recording through the whole adapter without the model.

A Text AI recording (ADR 0043) needs the provider's key in the environment variable its
`api_key_env` option names (never a file) and an input of synthetic text only, because the
repository is public. It records the server's reply, not the request or any header:

    uv run python scripts/record_ai_contract.py text_ai grade_gist --provider ollama \\
        --input synthetic_gist_input.json
"""

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import httpx

from listenup.ai.config import ProviderEntry, load_config
from listenup.ai.ports import Role
from listenup.ai.prompt_files import load_task
from listenup.ai.providers import faster_whisper, wav2vec2_ctc
from listenup.ai.providers.openai_compatible import OpenAICompatibleTextAI, parse_options
from listenup.ai.tasks import TASK_MODELS

RECORDINGS = Path(__file__).resolve().parents[1] / "tests" / "contract" / "recordings"


def configured_entry(role: Role, provider: str, model: str | None) -> ProviderEntry:
    """The role's entry for `provider` in ai.yaml, with `model` instead if given."""
    for entry in load_config().roles.get(role, ()):
        if entry.provider == provider:
            return entry if model is None else entry.model_copy(update={"model": model})
    return ProviderEntry(provider=provider, model=model or "default")


class _Recorder(httpx.AsyncBaseTransport):
    """Passes the call through and keeps the reply body (never request headers)."""

    def __init__(self, inner: httpx.AsyncBaseTransport | None = None) -> None:
        self.inner = inner or httpx.AsyncHTTPTransport()
        self.status = 0
        self.body: Any = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self.inner.handle_async_request(request)
        await response.aread()
        self.status, self.body = response.status_code, json.loads(response.content)
        return httpx.Response(response.status_code, content=response.content)


def record_text(
    provider: str,
    task: str,
    input: dict[str, Any],
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Call the configured Text AI server once and return the recording."""
    entry = configured_entry(Role.TEXT_AI, provider, None)
    recorder = _Recorder(transport)
    adapter = OpenAICompatibleTextAI(entry, transport=recorder)
    asyncio.run(adapter.generate(load_task(task), input, TASK_MODELS[task]))
    options = parse_options(entry)
    return {
        "provider": provider,
        "task": task,
        "synthetic": False,
        "note": f"Recorded from {entry.model}; input is synthetic text.",
        "input": input,
        "expect": {
            "path": "/" + options.base_url.split("/", 3)[3] + "/chat/completions",
            "sends_key": options.api_key_env is not None,
        },
        "response": {"status": recorder.status, "body": recorder.body},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", choices=["transcription", "alignment", "text_ai"])
    parser.add_argument("audio", type=Path, nargs="?", help="audio file; the task for text_ai")
    parser.add_argument("--provider", help="text_ai: the provider id in ai.yaml")
    parser.add_argument("--input", type=Path, help="text_ai: JSON file of synthetic input")
    parser.add_argument("--model", help="default: the model in ai.yaml")
    parser.add_argument("--text", help="reference text (alignment)")
    parser.add_argument("--name", help="recording name; default <provider>_<audio stem>")
    args = parser.parse_args()

    if args.port == "text_ai":
        task = str(args.audio)
        if task not in TASK_MODELS or not args.provider or not args.input:
            parser.error("text_ai needs a task name, --provider and --input")
        recording = record_text(args.provider, task, json.loads(args.input.read_text()))
        out = RECORDINGS / "text_ai" / f"{args.provider}_{task}.json"
        out.write_text(json.dumps(recording, indent=2, ensure_ascii=False) + "\n")
        print(f"wrote {out}")
        return
    if args.audio is None:
        parser.error("this port needs an audio file")
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
