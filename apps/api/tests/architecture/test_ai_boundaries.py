"""AI boundaries (NFR-AI-1, Architecture 4.3, ADR 0028), checked by reading every file.

- AI vendor libraries are imported only under `listenup/ai/providers/`. This catches
  imports inside functions and through `importlib.import_module("...")`, and libraries no
  file imports yet, which import-linter cannot list.
- Only grading and transcript import `listenup.ai`; any module added later is covered.
  The worker entry point may, to preload models before taking work.
"""

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "src" / "listenup"

# Top-level packages of AI vendors and local inference libraries. Add a library here
# before its first adapter.
VENDOR_LIBRARIES = frozenset(
    {
        "anthropic",
        "assemblyai",
        "cohere",
        "ctranslate2",
        "deepgram",
        "faster_whisper",
        "google.generativeai",
        "google.genai",
        "groq",
        "huggingface_hub",
        "llama_cpp",
        "mistralai",
        "ollama",
        "onnxruntime",
        "openai",
        "parselmouth",
        "speechbrain",
        "torch",
        "torchaudio",
        "transformers",
        "vosk",
        "whisper",
    }
)
AI_CALLERS = frozenset({"grading", "transcript"})


def imported_modules(tree: ast.AST) -> list[str]:
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.append(node.module)
            found.extend(f"{node.module}.{alias.name}" for alias in node.names)
        elif (
            isinstance(node, ast.Call)
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and (
                (isinstance(node.func, ast.Name) and node.func.id == "__import__")
                or (isinstance(node.func, ast.Attribute) and node.func.attr == "import_module")
            )
        ):
            found.append(node.args[0].value)
    return found


def is_vendor(name: str) -> bool:
    return any(name == lib or name.startswith(f"{lib}.") for lib in VENDOR_LIBRARIES)


def vendor_violations(package: Path) -> list[str]:
    providers = package / "ai" / "providers"
    found = []
    for path in sorted(package.rglob("*.py")):
        if path.is_relative_to(providers):
            continue
        for name in imported_modules(ast.parse(path.read_text(), filename=str(path))):
            if is_vendor(name):
                found.append(f"{path.relative_to(package)} imports {name}")
    return found


def ai_caller_violations(package: Path) -> list[str]:
    found = []
    for path in sorted(package.rglob("*.py")):
        relative = path.relative_to(package)
        if relative.parts[0] == "ai" or relative == Path("worker.py"):
            continue
        if (
            relative.parts[0] == "modules"
            and relative.parts[1:2]
            and relative.parts[1] in AI_CALLERS
        ):
            continue
        for name in imported_modules(ast.parse(path.read_text(), filename=str(path))):
            if name == "listenup.ai" or name.startswith("listenup.ai."):
                found.append(f"{relative} imports {name}")
    return found


def test_vendor_libraries_are_imported_only_by_provider_adapters() -> None:
    assert vendor_violations(PACKAGE) == []


def test_only_grading_and_transcript_import_the_ai_layer() -> None:
    assert ai_caller_violations(PACKAGE) == []


def test_the_checks_catch_forbidden_imports(tmp_path: Path) -> None:
    package = tmp_path / "listenup"
    (package / "ai" / "providers").mkdir(parents=True)
    (package / "modules" / "shadow").mkdir(parents=True)
    (package / "modules" / "grading").mkdir(parents=True)
    (package / "ai" / "providers" / "whisper_cpp.py").write_text("import faster_whisper\n")
    (package / "ai" / "gateway.py").write_text("from openai import OpenAI\n")
    (package / "modules" / "shadow" / "service.py").write_text(
        "import importlib\n\n"
        "def f():\n"
        "    import torch.nn\n"
        "    return importlib.import_module('transformers')\n"
        "from listenup.ai import gateway\n"
    )
    (package / "modules" / "grading" / "service.py").write_text("from listenup.ai import gateway\n")

    assert vendor_violations(package) == [
        "ai/gateway.py imports openai",
        "ai/gateway.py imports openai.OpenAI",
        "modules/shadow/service.py imports torch.nn",
        "modules/shadow/service.py imports transformers",
    ]
    assert ai_caller_violations(package) == [
        "modules/shadow/service.py imports listenup.ai",
        "modules/shadow/service.py imports listenup.ai.gateway",
    ]
