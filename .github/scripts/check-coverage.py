"""Fail before diff-cover if a runtime file is absent or its report path cannot resolve.

diff-cover only counts lines found in its report, treating missing files as 100%.
Use its own Cobertura lookup to require an entry for every runtime source file,
including empty packages and types-only files, before calculating changed lines.
Run with the backend's dev environment; reports are resolved from the app directory.
"""

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from fnmatch import fnmatchcase
from pathlib import Path

from diff_cover.git_path import GitPathTool  # type: ignore[import-untyped]
from diff_cover.violationsreporters.violations_reporter import (  # type: ignore[import-untyped]
    XmlCoverageReporter,
)


def excluded(name: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        # The shared list uses the Vitest extension brace pattern for tests.
        variants = (
            [pattern.replace("{ts,tsx}", extension) for extension in ("ts", "tsx")]
            if "{ts,tsx}" in pattern
            else [pattern]
        )
        for variant in variants:
            # **/ also matches zero directories (src/App.test.tsx, src/env.d.ts).
            if fnmatchcase(name, variant) or fnmatchcase(name, variant.replace("**/", "")):
                return True
    return False


def runtime_files(app_root: Path, app: str) -> list[Path]:
    source_root = app_root / ("src/listenup" if app == "api" else "src")
    if not source_root.is_dir():
        raise ValueError(f"Runtime source directory does not exist: {source_root}")
    if app == "api":
        return sorted(source_root.rglob("*.py"))
    patterns: list[str] = json.loads((app_root / "coverage-exclusions.json").read_text())
    return sorted(
        path
        for path in source_root.rglob("*")
        if path.is_file()
        and path.suffix in {".ts", ".tsx"}
        and not excluded(path.relative_to(app_root).as_posix(), patterns)
    )


def check_report(repo_root: Path, app: str, report_path: Path) -> None:
    app_root = repo_root / "apps" / app
    root = ET.parse(report_path).getroot()
    if root.tag != "coverage":
        raise ValueError(f"Expected a Cobertura coverage report: {report_path}")
    # Set the same cwd and use the same lookup as the following diff-cover command.
    os.chdir(app_root)
    GitPathTool.set_cwd(str(app_root))
    reporter = XmlCoverageReporter([root])
    missing = [
        path.relative_to(repo_root).as_posix()
        for path in runtime_files(app_root, app)
        if reporter.get_src_path_line_nodes_cobertura(
            0, root, path.relative_to(repo_root).as_posix()
        )
        is None
    ]
    if missing:
        raise ValueError(
            "Runtime files missing from the coverage report or with unmatched paths:\n"
            + "\n".join(f"  {name}" for name in missing)
        )
    print(f"{app}: every runtime source file resolves in {report_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", choices=("api", "web"))
    parser.add_argument("report", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    try:
        check_report(args.repo_root.resolve(), args.app, args.report.resolve())
    except (OSError, ValueError, ET.ParseError) as error:
        print(f"Coverage completeness check failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
