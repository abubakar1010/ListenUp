"""Fetch public inputs through inherited proxy/TLS settings. Stop on any download error."""

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

CMU = "b88ad416e092c4dfdffc6071f4b8e2d057a160f9"
PHONE = "ae45363bf3413b374fecd9dc8bc1df0e24c3b7f4"
FILES = {
    "bdl.parquet": (
        "data/bdl-00000-of-00001-0c683a89629915f1.parquet",
        "1b2a86eaed50ea338325ad718e3f2e8e91acf32105aa2eeef08a3c2aa60723c6",
    ),
    "slt.parquet": (
        "data/slt-00000-of-00001-3dd3ad8fa62951ad.parquet",
        "9f76b0da2b34679c65b4d55014377a9f6a04f8f9a73dc8af9134f9481a4d6ad7",
    ),
    "clb.parquet": (
        "data/clb-00000-of-00001-8f46506de584c7ae.parquet",
        "4cc4b4342d49d542b1c4c4f2684bb02aab1eb9c8a654c186639ef7b692c508bf",
    ),
}


def fetch(url, path, expected=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        tmp = path.with_suffix(path.suffix + ".partial")
        # No bypass, retries, alternate endpoints, or disabled TLS on denial.
        with urlopen(url, timeout=120) as source, tmp.open("wb") as target:
            while block := source.read(1024 * 1024):
                target.write(block)
        tmp.rename(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if expected and digest != expected:
        raise ValueError(f"Checksum mismatch: {path.name}")
    return digest


def main():
    from huggingface_hub import snapshot_download

    parser = argparse.ArgumentParser()
    parser.add_argument("data", type=Path)
    parser.add_argument("--whisper-revision", required=True)
    args = parser.parse_args()
    records = {}
    for name, (remote, digest) in FILES.items():
        records[name] = fetch(
            f"https://huggingface.co/datasets/MikhailT/cmu-arctic/resolve/{CMU}/{remote}",
            args.data / name,
            digest,
        )
    for name in [
        "pytorch_model.bin",
        "config.json",
        "preprocessor_config.json",
        "vocab.json",
    ]:
        records["phone/" + name] = fetch(
            f"https://huggingface.co/facebook/wav2vec2-lv-60-espeak-cv-ft/resolve/{PHONE}/{name}",
            args.data / "phone" / name,
            "3173bde9e9ce490fa0f989e413c42f25bc1820c020adc1e6b9b87025b3cfcc5e"
            if name == "pytorch_model.bin"
            else None,
        )
    records["word.pth"] = fetch(
        "https://download.pytorch.org/torchaudio/models/wav2vec2_fairseq_base_ls960_asr_ls960.pth",
        args.data / "word.pth",
        "488fd4f16de84438ffc945334278c1b9fb9b7159a806c1080b16111a958c945d",
    )
    snapshot_download(
        "Systran/faster-whisper-small.en",
        revision=args.whisper_revision,
        allow_patterns=["config.json", "model.bin", "tokenizer.json", "vocabulary.txt"],
        local_dir=args.data / "whisper",
    )
    for p in (args.data / "whisper").glob("*"):
        if p.is_file():
            records["whisper/" + p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    (args.data / "input-hashes.json").write_text(json.dumps(records, indent=2))


if __name__ == "__main__":
    main()
