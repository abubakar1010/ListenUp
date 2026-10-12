"""Coverage enforcement rejects omitted files as well as uncovered executable lines."""

import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
CHECKER = REPO / ".github/scripts/check-coverage.py"


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for app in ("api", "web"):
        (tmp_path / f"apps/{app}/src").mkdir(parents=True)
    (tmp_path / "apps/api/src/listenup").mkdir()
    (tmp_path / "apps/api/src/listenup/__init__.py").write_text("")
    exclusions = REPO / "apps/web/coverage-exclusions.json"
    shutil.copy(exclusions, tmp_path / "apps/web/coverage-exclusions.json")
    return tmp_path


def source(checkout: Path, app: str, name: str, text: str) -> Path:
    path = checkout / f"apps/{app}" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def report(checkout: Path, app: str, entries: dict[str, list[int]]) -> Path:
    """Cobertura entries use the app-relative filenames emitted by our producers."""
    root = ET.Element("coverage")
    ET.SubElement(ET.SubElement(root, "sources"), "source").text = "."
    classes = ET.SubElement(ET.SubElement(ET.SubElement(root, "packages"), "package"), "classes")
    if app == "api":
        entries = {"src/listenup/__init__.py": [], **entries}
    for filename, hits in entries.items():
        lines = ET.SubElement(ET.SubElement(classes, "class", filename=filename), "lines")
        for number, count in enumerate(hits, 1):
            ET.SubElement(lines, "line", number=str(number), hits=str(count))
    path = checkout / f"apps/{app}/coverage.xml"
    ET.ElementTree(root).write(path)
    return path


def gate(
    checkout: Path, app: str, report_path: Path, changed: list[Path]
) -> subprocess.CompletedProcess[str]:
    cwd = checkout / f"apps/{app}"
    result = subprocess.run(
        [sys.executable, str(CHECKER), "--repo-root", str(checkout), app, str(report_path)],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        return result
    diff = checkout / "changes.diff"
    chunks = []
    for path in changed:
        name = path.relative_to(checkout).as_posix()
        lines = path.read_text().splitlines()
        chunks.append(
            f"diff --git a/{name} b/{name}\nnew file mode 100644\n"
            f"--- /dev/null\n+++ b/{name}\n@@ -0,0 +1,{len(lines)} @@\n"
            + "".join(f"+{line}\n" for line in lines)
        )
    diff.write_text("".join(chunks))
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "diff_cover.diff_cover_tool",
            str(report_path),
            "--diff-file",
            str(diff),
            "--ignore-staged",
            "--ignore-unstaged",
            "--fail-under",
            "90",
        ],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def test_never_imported_namespace_module_is_reported_and_rejected(checkout: Path) -> None:
    app = checkout / "apps/api"
    shutil.copy(REPO / "apps/api/pyproject.toml", app / "pyproject.toml")
    source(checkout, "api", "src/listenup/known.py", "answer = 42\n")
    untested = source(
        checkout, "api", "src/listenup/new_namespace/rule.py", "def rule():\n    return 99\n"
    )
    runner = source(
        checkout,
        "api",
        "runner.py",
        'import sys\nsys.path.insert(0, "src")\nimport listenup.known\n',
    )
    subprocess.run([sys.executable, "-m", "coverage", "run", str(runner)], cwd=app, check=True)
    subprocess.run([sys.executable, "-m", "coverage", "xml"], cwd=app, check=True)
    path = app / "coverage/coverage.xml"
    assert "new_namespace/rule.py" in {
        node.get("filename") for node in ET.parse(path).findall(".//class")
    }
    result = gate(checkout, "api", path, [untested])
    assert result.returncode != 0
    assert "new_namespace/rule.py" in result.stdout
    assert "Coverage: 0%" in result.stdout


@pytest.mark.parametrize("app,name", [("api", "src/listenup/new.py"), ("web", "src/new.ts")])
def test_missing_runtime_file_cannot_hide_behind_a_covered_file(
    checkout: Path, app: str, name: str
) -> None:
    covered_name = "src/listenup/covered.py" if app == "api" else "src/covered.ts"
    covered = source(
        checkout, app, covered_name, "value = 1\n" if app == "api" else "export const value = 1;\n"
    )
    missing = source(
        checkout, app, name, "value = 2\n" if app == "api" else "export const value = 2;\n"
    )
    path = report(checkout, app, {covered_name: [1]})
    result = gate(checkout, app, path, [covered, missing])
    assert result.returncode != 0
    assert name in result.stderr


@pytest.mark.parametrize(
    "app,name", [("api", "src/listenup/rule.py"), ("web", "src/features/rule.ts")]
)
def test_mismatched_report_paths_fail(checkout: Path, app: str, name: str) -> None:
    changed = source(
        checkout, app, name, "value = 1\n" if app == "api" else "export const value = 1;\n"
    )
    path = report(checkout, app, {f"/another/checkout/{name}": [0]})
    result = gate(checkout, app, path, [changed])
    assert result.returncode != 0
    assert name in result.stderr


@pytest.mark.parametrize(
    "app,name", [("api", "src/listenup/rule.py"), ("web", "src/features/rule.tsx")]
)
@pytest.mark.parametrize("covered_lines,passes", [(0, False), (8, False), (9, True), (10, True)])
def test_changed_line_threshold_is_preserved(
    checkout: Path, app: str, name: str, covered_lines: int, passes: bool
) -> None:
    text = "".join(
        f"value_{i} = {i}\n" if app == "api" else f"export const value_{i} = {i};\n"
        for i in range(10)
    )
    changed = source(checkout, app, name, text)
    path = report(checkout, app, {name: [1] * covered_lines + [0] * (10 - covered_lines)})
    result = gate(checkout, app, path, [changed])
    assert (result.returncode == 0) is passes, result.stdout + result.stderr


@pytest.mark.parametrize("app", ["api", "web"])
def test_documentation_and_test_only_changes_pass(checkout: Path, app: str) -> None:
    name = "src/listenup/rule.py" if app == "api" else "src/rule.ts"
    source(checkout, app, name, "value = 1\n" if app == "api" else "export const value = 1;\n")
    doc = source(checkout, app, "README.md", "Documentation only.\n")
    test = source(
        checkout,
        app,
        "tests/test_rule.py" if app == "api" else "src/rule.test.ts",
        "// Test only\n",
    )
    path = report(checkout, app, {name: [0]})
    assert gate(checkout, app, path, [doc, test]).returncode == 0


def test_only_declared_web_helpers_and_generated_types_are_excluded(checkout: Path) -> None:
    names = [
        "src/test-setup.ts",
        "src/test-utils.tsx",
        "src/features/session/testApi.ts",
        "src/features/session/fixtures.ts",
        "src/features/blind/fixtures.ts",
        "src/api/schema.ts",
        "src/env.d.ts",
        "src/root.test.tsx",
        "src/nested/a.test.ts",
    ]
    changed = [source(checkout, "web", name, "export {};\n") for name in names]
    path = report(checkout, "web", {})
    assert gate(checkout, "web", path, changed).returncode == 0
    runtime = source(checkout, "web", "src/features/other/fixtures.ts", "export const value = 1;\n")
    assert gate(checkout, "web", path, [runtime]).returncode != 0


def test_empty_python_package_and_types_only_web_file_are_valid(checkout: Path) -> None:
    path = report(checkout, "api", {})
    assert gate(checkout, "api", path, []).returncode == 0
    changed = source(checkout, "web", "src/types.ts", "export interface Result { value: number }\n")
    path = report(checkout, "web", {"src/types.ts": []})
    assert gate(checkout, "web", path, [changed]).returncode == 0
