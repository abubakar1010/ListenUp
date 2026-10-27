"""Check the #106 (gist) and #107 (Shadow) golden-set files in ai-evals/.

Run from apps/api:

    uv run python scripts/check_golden_sets.py
    uv run python scripts/check_golden_sets.py --require-complete --suite gist
    uv run python scripts/check_golden_sets.py --suite gist --agreement

Without --require-complete it validates the committed `*.template.json` files and,
when `dataset.json` and its sidecars exist, their format, privacy and referential
rules. With --require-complete it also enforces the coverage matrix in each set's
`coverage-matrix.md`, and fails while `dataset.json` is missing. Exit code 0 means no
problems, 1 means problems were printed, 2 is a usage error. The thresholds below are
the kit's proposed minimums; keep them in step with the matrices.
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from statistics import mean
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError

from listenup.ai.evals.models import Dataset, Grade

SUITES = ("gist", "shadow")
DIRECTORIES = {"gist": "gists", "shadow": "shadow"}
CASES = range(45, 56)  # "about 50"
PASSAGES = range(8, 13)  # "about 10"
GIST_LEVELS = ("Needs work", "Fair", "Good", "Excellent")
MIN_PER_LEVEL = 5
GIST_AT_CASES = ("at-10", "at-11", "at-12", "at-13")
MIN_PER_AT_CASE = 3
MIN_PER_CEFR = 8
MIN_ACCENT_GROUPS = 4
MIN_SPEAKERS_PER_GROUP = 3
MIN_AT_17_PAIRS = 3
MIN_FILLER_CASES = 10  # recordings with, and recordings without, fillers
SEGMENT_SECONDS = (30, 90)  # FR-SH-1: 60 to 90 s, or a whole 30 to 60 s passage
LABELS = ("good", "needs_work", "missed")

PERSONAL_DATA = (
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    re.compile(r"X-Amz-|[?&](?:signature|token|key)=", re.IGNORECASE),
    re.compile(r"(?<!\w)\+?\d[\d ()-]{8,}\d"),
)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TeacherGrade(Strict):
    case: str
    teacher: str = Field(pattern=r"^T[0-9]{1,2}$")  # a code; names never enter the repo
    grade: Grade
    covered_points: tuple[str, ...] = ()


class TeacherGrades(Strict):
    version: Literal[1]
    dataset: str
    grades: tuple[TeacherGrade, ...]


class Passage(Strict):
    id: str = Field(pattern=r"^[a-z0-9-]{1,32}$")
    title: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    speaker_accent: str = Field(min_length=1)
    licence: str = Field(min_length=1)
    source_url: HttpUrl
    duration_seconds: Annotated[float, Field(gt=0)]


class Passages(Strict):
    version: Literal[1]
    passages: tuple[Passage, ...]


class WordLabel(Strict):
    word: str = Field(min_length=1)
    label: Literal["good", "needs_work", "missed"]


class CaseLabels(Strict):
    case: str
    words: tuple[WordLabel, ...] = Field(min_length=1)


class WordLabels(Strict):
    version: Literal[1]
    labels: tuple[CaseLabels, ...]


def _load(path: Path, model: type[BaseModel], problems: list[str]) -> Any:
    try:
        return model.model_validate_json(path.read_text(encoding="utf-8"))
    except (ValidationError, ValueError) as error:
        first = str(error).splitlines()
        problems.append(f"{path.name}: invalid ({'; '.join(first[:3])})")
        return None


def _scan_personal_data(path: Path, problems: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    if any(pattern.search(text) for pattern in PERSONAL_DATA):
        problems.append(f"{path.name}: possible personal data (email, phone, signed URL)")


def _tags(case: Any, prefix: str) -> list[str]:
    return [t.removeprefix(prefix) for t in case.tags if t.startswith(prefix)]


def _check_template(suite: str, directory: Path, problems: list[str]) -> None:
    for path in sorted(directory.glob("*.template.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            problems.append(f"{path.name}: not valid JSON")
            continue
        if any(data.get(key) for key in ("cases", "grades", "passages", "labels")):
            problems.append(f"{path.name}: templates must stay empty")
        if path.name == "dataset.template.json" and (
            data.get("kind") != "teacher" or data.get("suite") != suite or data.get("version") != 1
        ):
            problems.append("dataset.template.json: needs version 1, kind teacher and the suite")


def _check_dataset(
    suite: str,
    dataset: Dataset,
    grades: TeacherGrades | None,
    passages: Passages | None,
    labels: WordLabels | None,
    complete: bool,
    problems: list[str],
) -> None:
    if dataset.kind != "teacher" or dataset.suite != suite:
        problems.append(f"dataset.json: must be a teacher {suite} dataset")
    cases = dataset.cases
    ids = {case.id for case in cases}
    passage_ids = {p.id for p in passages.passages} if passages else set()
    for case in cases:
        for passage in _tags(case, "passage:"):
            if passages and passage not in passage_ids:
                problems.append(f"{case.id}: passage {passage} is not in passages.json")
    if grades:
        graded = {g.case for g in grades.grades}
        for missing in sorted(ids - graded):
            problems.append(f"{missing}: no teacher grade in teacher-grades.json")
        for unknown in sorted(graded - ids):
            problems.append(f"teacher-grades.json: grade for unknown case {unknown}")
    elif complete:
        problems.append("teacher-grades.json is missing")
    if not complete:
        return
    if len(cases) not in CASES:
        problems.append(f"{len(cases)} cases; about 50 needed ({CASES.start} to {CASES.stop - 1})")
    used = {p for case in cases for p in _tags(case, "passage:")}
    if len(used) not in PASSAGES or any(len(_tags(c, "passage:")) != 1 for c in cases):
        problems.append(f"{len(used)} passages in use; about 10 needed, one passage: tag per case")
    if suite == "gist":
        _gist_matrix(cases, problems)
    else:
        _shadow_matrix(cases, labels, problems)


def _gist_matrix(cases: Any, problems: list[str]) -> None:
    by_level: dict[str | None, int] = defaultdict(int)
    for case in cases:
        by_level[case.expected.level] += 1
    for level in GIST_LEVELS:
        if by_level[level] < MIN_PER_LEVEL:
            problems.append(f"level {level}: {by_level[level]} cases, need {MIN_PER_LEVEL}")
    for tag in GIST_AT_CASES:
        count = sum(tag in case.tags for case in cases)
        if count < MIN_PER_AT_CASE:
            problems.append(f"{tag}: {count} cases, need {MIN_PER_AT_CASE}")
    for case in cases:
        if "at-10" in case.tags and case.expected.level not in ("Good", "Excellent"):
            problems.append(f"{case.id}: at-10 case must be graded Good or Excellent")
        if "at-11" in case.tags and case.expected.level != "Needs work":
            problems.append(f"{case.id}: at-11 case must be graded Needs work")
    for band in ("b1", "b2", "c1"):
        count = sum(f"cefr:{band}" in case.tags for case in cases)
        if count < MIN_PER_CEFR:
            problems.append(f"cefr:{band}: {count} cases, need {MIN_PER_CEFR}")
    clean = {
        pair: case for case in cases if "kind:clean" in case.tags for pair in _tags(case, "pair:")
    }
    for case in cases:
        if "at-12" not in case.tags:
            continue
        twin = next((clean[p] for p in _tags(case, "pair:") if p in clean), None)
        if twin is None:
            problems.append(
                f"{case.id}: at-12 case needs a pair: tag shared with a kind:clean case"
            )
        elif twin.expected.level != case.expected.level:
            problems.append(f"{case.id}: at-12 case must have the same level as its clean version")


def _shadow_matrix(cases: Any, labels: WordLabels | None, problems: list[str]) -> None:
    speakers = defaultdict(set)
    for case in cases:
        group, speaker = _tags(case, "accent:"), _tags(case, "speaker:")
        if len(group) != 1 or len(speaker) != 1:
            problems.append(f"{case.id}: needs one accent: tag and one speaker: tag")
            continue
        speakers[group[0]].add(speaker[0])
        for path in (case.input.recording, case.input.reference_audio):
            if not path.startswith("external/") or ".." in path:
                problems.append(f"{case.id}: audio must be a relative external/ reference")
        seconds = case.context.audio_seconds
        if seconds is None or not SEGMENT_SECONDS[0] <= seconds <= SEGMENT_SECONDS[1]:
            problems.append(f"{case.id}: context.audio_seconds must be set, 30 to 90")
    strong = [g for g, s in speakers.items() if len(s) >= MIN_SPEAKERS_PER_GROUP]
    if len(strong) < MIN_ACCENT_GROUPS:
        problems.append(
            f"{len(strong)} accent groups with {MIN_SPEAKERS_PER_GROUP}+ speakers; "
            f"need {MIN_ACCENT_GROUPS} (groups: "
            + ", ".join(f"{g}={len(s)} speakers" for g, s in sorted(speakers.items()))
            + ")"
        )
    pairs: dict[str, dict[str, Any]] = defaultdict(dict)
    for case in cases:
        for pair in _tags(case, "pair:"):
            for delivery in _tags(case, "delivery:"):
                pairs[pair][delivery] = case
    valid = 0
    for pair, sides in pairs.items():
        clear, mumbled = sides.get("clear"), sides.get("mumbled")
        if not (clear and mumbled):
            continue
        if _tags(clear, "passage:") != _tags(mumbled, "passage:"):
            problems.append(f"pair {pair}: at-17 versions must use the same passage")
        elif mumbled.expected.overall >= clear.expected.overall:
            problems.append(f"pair {pair}: at-17 mumbled version must score lower overall")
        else:
            valid += 1
    if valid < MIN_AT_17_PAIRS:
        problems.append(f"{valid} at-17 clear/mumbled pairs, need {MIN_AT_17_PAIRS}")
    fillers = sum((case.expected.filler_count or 0) > 0 for case in cases)
    if fillers < MIN_FILLER_CASES or len(cases) - fillers < MIN_FILLER_CASES:
        problems.append(f"filler counts: need {MIN_FILLER_CASES}+ recordings with and without")
    labelled = {entry.case for entry in labels.labels} if labels else set()
    if missing := {case.id for case in cases} - labelled:
        problems.append(f"word labels missing for {len(missing)} cases")


def check_suite(suite: str, directory: Path, *, require_complete: bool = False) -> list[str]:
    problems: list[str] = []
    _check_template(suite, directory, problems)
    dataset_path = directory / "dataset.json"
    if not dataset_path.exists():
        if require_complete:
            problems.append("dataset.json is missing: no real data has been collected yet")
        return problems
    for path in directory.glob("*.json"):
        if not path.name.endswith(".template.json"):
            _scan_personal_data(path, problems)
    dataset = _load(dataset_path, Dataset, problems)
    sidecars: dict[str, Any] = {}
    for name, model in (
        ("teacher-grades.json", TeacherGrades),
        ("passages.json", Passages),
        ("word-labels.json", WordLabels),
    ):
        path = directory / name
        needed = name != "word-labels.json" or suite == "shadow"
        if path.exists() and needed:
            sidecars[name] = _load(path, model, problems)
        elif needed and require_complete:
            problems.append(f"{name} is missing")
    if dataset is not None:
        _check_dataset(
            suite,
            dataset,
            sidecars.get("teacher-grades.json"),
            sidecars.get("passages.json"),
            sidecars.get("word-labels.json"),
            require_complete,
            problems,
        )
    return problems


def agreement(grades_path: Path) -> dict[str, Any]:
    """Level agreement and mean absolute score difference between teachers.

    Compared over every pair of teachers who graded the same case, so a case graded
    by two teachers is one pair and a case graded by three is three.
    """
    grades = TeacherGrades.model_validate_json(grades_path.read_text(encoding="utf-8"))
    by_case: dict[str, list[TeacherGrade]] = defaultdict(list)
    for entry in grades.grades:
        by_case[entry.case].append(entry)
    pairs = [pair for entries in by_case.values() for pair in combinations(entries, 2)]
    differences: dict[str, list[float]] = defaultdict(list)
    for a, b in pairs:
        for name in a.grade.scores:
            differences[name].append(abs(a.grade.scores[name] - b.grade.scores[name]))
        differences["overall"].append(abs(a.grade.overall - b.grade.overall))
        if a.grade.filler_count is not None and b.grade.filler_count is not None:
            differences["filler_count"].append(abs(a.grade.filler_count - b.grade.filler_count))
    levels = [(a.grade.level, b.grade.level) for a, b in pairs if a.grade.level and b.grade.level]
    return {
        "double_graded_cases": sum(len(entries) > 1 for entries in by_case.values()),
        "teacher_pairs": len(pairs),
        "level_agreement": mean(x == y for x, y in levels) if levels else None,
        "mean_abs_difference": {name: mean(values) for name, values in differences.items()},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--suite", choices=[*SUITES, "all"], default="all")
    parser.add_argument("--dir", type=Path, help="one suite's directory (needs --suite)")
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument("--agreement", action="store_true", help="report teacher agreement")
    args = parser.parse_args(argv)
    if args.dir and args.suite == "all":
        parser.error("--dir needs --suite")
    root = Path(__file__).resolve().parents[3] / "ai-evals"
    suites = SUITES if args.suite == "all" else (args.suite,)
    failed = False
    for suite in suites:
        directory = args.dir or root / DIRECTORIES[suite]
        if args.agreement:
            path = directory / "teacher-grades.json"
            report = json.dumps(agreement(path), indent=2) if path.exists() else "no grades"
            print(f"{suite}: {report}")
            continue
        problems = check_suite(suite, directory, require_complete=args.require_complete)
        print(f"{suite}: {'ok' if not problems else f'{len(problems)} problem(s)'}")
        for problem in problems:
            print(f"  - {problem}")
        failed |= bool(problems)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
