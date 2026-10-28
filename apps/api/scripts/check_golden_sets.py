"""Check the #106 (gist) and #107 (Shadow) golden-set files in ai-evals/.

Run from apps/api:

    uv run python scripts/check_golden_sets.py
    uv run python scripts/check_golden_sets.py --require-complete --suite gist
    uv run python scripts/check_golden_sets.py --suite gist --agreement

Without --require-complete it validates the committed `*.template.json` files and,
when `dataset.json` and its sidecars exist, their format, privacy and referential
rules (tags, identifiers, audio references, teacher grades, key points, word labels).
With --require-complete it also enforces the coverage matrix in each set's
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

from listenup.ai.evals.models import GIST_DIMENSIONS, SHADOW_MEASURES, Dataset, Grade

SUITES = ("gist", "shadow")
DIRECTORIES = {"gist": "gists", "shadow": "shadow"}
CASES = range(45, 56)  # "about 50"
PASSAGES = range(8, 13)  # "about 10"
GIST_LEVELS = ("Needs work", "Fair", "Good", "Excellent")
MIN_PER_LEVEL = 5
GIST_AT_CASES = ("at-10", "at-11", "at-12", "at-13")
MIN_PER_AT_CASE = 3
MIN_PER_CEFR = 8
KEY_POINTS = range(3, 7)  # SRS 5.2.1: 3 to 6 key points, one of them the main idea
MIN_PASSAGE_ACCENTS = 4  # distinct reference-speaker accents across the passages
MAX_PASSAGES_PER_ACCENT = 3
MIN_ACCENT_GROUPS = 4
MIN_SPEAKERS_PER_GROUP = 3
MIN_AT_17_PAIRS = 3
MIN_FILLER_CASES = 10  # recordings with, and recordings without, fillers
SEGMENT_SECONDS = (30, 90)  # FR-SH-1: 60 to 90 s, or a whole 30 to 60 s passage
SEGMENT_TOLERANCE_SECONDS = 1.0  # a recording's audio_seconds vs its segment's duration
AUDIO_SUFFIXES = (".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac", ".webm", ".mp4")

TAG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*(?::[a-z0-9]+(?:-[a-z0-9]+)*)?$")
CASE_ID = {"gist": re.compile(r"^g[0-9]{2,3}$"), "shadow": re.compile(r"^r[0-9]{2,3}$")}
SPEAKER = re.compile(r"^s[0-9]{1,3}$")  # a code; the register stays outside the repository
RECORDING = re.compile(r"^external/rec-[0-9]{1,3}\.wav$")
REFERENCE_AUDIO = re.compile(r"^external/ref-[a-z0-9-]{1,32}\.wav$")
WORD = re.compile(r"[a-z0-9']+")
CURLY_APOSTROPHE = "\N{RIGHT SINGLE QUOTATION MARK}"

PERSONAL_DATA = (
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    re.compile(r"X-Amz-|[?&](?:signature|token|key)=", re.IGNORECASE),
    # A phone number: +country code, a leading 0 and ten or more digits, or 3-3-4 groups.
    # Dates, long counts and digits inside identifiers or URLs are not matched.
    re.compile(
        r"(?<![\w/.+-])(?:\+\d[\d ()-]{7,}\d|0[1-9][\d ()-]{8,}\d"
        r"|\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4})(?![\w-])"
    ),
)

TEMPLATES = {
    "dataset.template.json": {"version", "id", "kind", "suite", "source", "cases"},
    "teacher-grades.template.json": {"version", "dataset", "grades"},
    "passages.template.json": {"version", "passages"},
    "word-labels.template.json": {"version", "labels"},
}


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


def _tags(case: Any, prefix: str) -> list[str]:
    return [t.removeprefix(prefix) for t in case.tags if t.startswith(prefix)]


def _words(text: str) -> list[str]:
    return WORD.findall(text.lower().replace(CURLY_APOSTROPHE, "'"))


def _check_files(directory: Path, problems: list[str]) -> None:
    """Personal data in any JSON file, and no audio or `external/` assets in the repo."""
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        if path.suffix.lower() in AUDIO_SUFFIXES or "external" in relative.parts:
            problems.append(f"{relative}: audio and external assets stay outside the repository")
        elif path.suffix == ".json" and any(
            pattern.search(path.read_text(encoding="utf-8")) for pattern in PERSONAL_DATA
        ):
            problems.append(f"{path.name}: possible personal data (email, phone, signed URL)")


def _check_templates(suite: str, directory: Path, problems: list[str]) -> None:
    for path in sorted(directory.glob("*.template.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            problems.append(f"{path.name}: not valid JSON")
            continue
        if not isinstance(data, dict):
            problems.append(f"{path.name}: must be a JSON object")
            continue
        allowed = TEMPLATES.get(path.name)
        if allowed is None:
            problems.append(f"{path.name}: unknown template file")
        elif extra := set(data) - allowed:
            problems.append(f"{path.name}: unexpected keys {sorted(extra)}")
        if any(data.get(key) for key in ("cases", "grades", "passages", "labels")):
            problems.append(f"{path.name}: templates must stay empty")
        if path.name == "dataset.template.json" and (
            data.get("kind") != "teacher" or data.get("suite") != suite or data.get("version") != 1
        ):
            problems.append("dataset.template.json: needs version 1, kind teacher and the suite")


def _check_tags(suite: str, cases: Any, problems: list[str]) -> None:
    for case in cases:
        if not CASE_ID[suite].match(case.id):
            problems.append(f"{case.id}: case id must look like {CASE_ID[suite].pattern}")
        if len(set(case.tags)) != len(case.tags):
            problems.append(f"{case.id}: duplicate tag")
        for tag in case.tags:
            if not TAG.match(tag):
                problems.append(
                    f"{case.id}: invalid tag {tag!r} (lower case, kebab-case, no empty value)"
                )


def _check_passage_tags(cases: Any, passages: Passages | None, problems: list[str]) -> None:
    if passages is None:
        return
    seen: set[str] = set()
    for passage in passages.passages:
        if passage.id in seen:
            problems.append(f"duplicate passage id {passage.id} in passages.json")
        seen.add(passage.id)
    for case in cases:
        for passage_id in _tags(case, "passage:"):
            if passage_id not in seen:
                problems.append(f"{case.id}: passage {passage_id} is not in passages.json")


def _check_gist_content(cases: Any, problems: list[str]) -> None:
    references: dict[str, set[Any]] = defaultdict(set)
    for case in cases:
        points = case.input.key_points
        if len(points) not in KEY_POINTS:
            problems.append(f"{case.id}: needs 3 to 6 key points, has {len(points)}")
        if [p.id for p in points] != [f"kp{n}" for n in range(1, len(points) + 1)]:
            problems.append(f"{case.id}: key point ids must be kp1, kp2, ... in order")
        if sum(p.kind == "main" for p in points) != 1:
            problems.append(f"{case.id}: needs exactly one main key point")
        reference = (case.input.transcript, tuple((p.id, p.text, p.kind) for p in points))
        for passage_id in _tags(case, "passage:"):
            references[passage_id].add(reference)
    for passage_id, found in sorted(references.items()):
        if len(found) > 1:
            problems.append(f"passage {passage_id}: cases disagree on transcript or key points")


def _check_grades(suite: str, dataset: Dataset, grades: TeacherGrades, problems: list[str]) -> None:
    cases = {case.id: case for case in dataset.cases}
    names = GIST_DIMENSIONS if suite == "gist" else SHADOW_MEASURES
    if grades.dataset != dataset.id:
        problems.append(f"teacher-grades.json: grades are for another dataset ({grades.dataset})")
    by_case: dict[str, list[TeacherGrade]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    for entry in grades.grades:
        by_case[entry.case].append(entry)
        if (entry.case, entry.teacher) in seen:
            problems.append(f"{entry.case}: duplicate grade from {entry.teacher}")
        seen.add((entry.case, entry.teacher))
        case = cases.get(entry.case)
        if case is None:
            problems.append(f"teacher-grades.json: grade for unknown case {entry.case}")
            continue
        where = f"{entry.case}/{entry.teacher}"
        if set(entry.grade.scores) != names:
            problems.append(f"{where}: scores must be exactly {sorted(names)}")
        if suite == "gist":
            if entry.grade.level is None:
                problems.append(f"{where}: a gist grade needs a level")
            known = {p.id for p in case.input.key_points}
            if not set(entry.covered_points) <= known:
                problems.append(
                    f"{where}: covered_points names a key point that is not in the case"
                )
            main = {p.id for p in case.input.key_points if p.kind == "main"}
            if "at-11" in case.tags and main & set(entry.covered_points):
                problems.append(f"{where}: at-11 gist cannot cover the main idea")
        else:
            if entry.grade.filler_count is None:
                problems.append(f"{where}: a Shadow grade needs filler_count")
            if entry.covered_points:
                problems.append(f"{where}: covered_points belongs to gist grades only")
    for missing in sorted(set(cases) - set(by_case)):
        problems.append(f"{missing}: no teacher grade in teacher-grades.json")
    for case_id, entries in by_case.items():
        if case_id in cases and len(entries) == 1 and cases[case_id].expected != entries[0].grade:
            problems.append(f"{case_id}: expected differs from the only teacher grade")


def _check_labels(dataset: Dataset, labels: WordLabels, problems: list[str]) -> None:
    cases = {case.id: case for case in dataset.cases}
    seen: set[str] = set()
    for entry in labels.labels:
        if entry.case in seen:
            problems.append(f"{entry.case}: duplicate word labels")
        seen.add(entry.case)
        case = cases.get(entry.case)
        if case is None:
            problems.append(f"word-labels.json: labels for unknown case {entry.case}")
        elif [" ".join(_words(w.word)) for w in entry.words] != _words(case.input.reference_text):
            problems.append(f"{entry.case}: word labels do not match reference_text, word for word")


def _check_shadow_format(
    dataset: Dataset, passages: Passages | None, complete: bool, problems: list[str]
) -> None:
    durations = {p.id: p.duration_seconds for p in passages.passages} if passages else {}
    for passage in passages.passages if passages else ():
        if not SEGMENT_SECONDS[0] <= passage.duration_seconds <= SEGMENT_SECONDS[1]:
            problems.append(f"passage {passage.id}: segment must be 30 to 90 s (FR-SH-1)")
    speaker_groups: dict[str, set[str]] = defaultdict(set)
    for case in dataset.cases:
        group, speaker = _tags(case, "accent:"), _tags(case, "speaker:")
        if len(group) != 1 or len(speaker) != 1:
            problems.append(f"{case.id}: needs one accent: tag and one speaker: tag")
        elif not SPEAKER.match(speaker[0]):
            problems.append(f"{case.id}: speaker: tag must be a code like s12, not a name")
        else:
            speaker_groups[speaker[0]].add(group[0])
        if not RECORDING.match(case.input.recording):
            problems.append(f"{case.id}: recording must be external/rec-<n>.wav")
        if not REFERENCE_AUDIO.match(case.input.reference_audio):
            problems.append(f"{case.id}: reference_audio must be external/ref-<segment>.wav")
        seconds = case.context.audio_seconds
        if seconds is None:
            if complete:
                problems.append(f"{case.id}: context.audio_seconds must be set, 30 to 90")
        elif not SEGMENT_SECONDS[0] <= seconds <= SEGMENT_SECONDS[1]:
            problems.append(f"{case.id}: context.audio_seconds must be set, 30 to 90")
        else:
            for passage_id in _tags(case, "passage:"):
                known = durations.get(passage_id)
                if known is not None and abs(known - seconds) > SEGMENT_TOLERANCE_SECONDS:
                    problems.append(f"{case.id}: audio_seconds differs from the segment duration")
    for speaker, groups in sorted(speaker_groups.items()):
        if len(groups) > 1:
            problems.append(f"speaker {speaker} is in more than one accent group")


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
    _check_tags(suite, cases, problems)
    _check_passage_tags(cases, passages, problems)
    if suite == "gist":
        _check_gist_content(cases, problems)
    else:
        _check_shadow_format(dataset, passages, complete, problems)
        if labels is not None:
            _check_labels(dataset, labels, problems)
    if grades is not None:
        _check_grades(suite, dataset, grades, problems)
    if not complete:
        return
    if len(cases) not in CASES:
        problems.append(f"{len(cases)} cases; about 50 needed ({CASES.start} to {CASES.stop - 1})")
    used = {p for case in cases for p in _tags(case, "passage:")}
    if len(used) not in PASSAGES or any(len(_tags(c, "passage:")) != 1 for c in cases):
        problems.append(f"{len(used)} passages in use; about 10 needed, one passage: tag per case")
    if passages is not None:
        _check_passage_variety(passages, used, problems)
    if suite == "gist":
        _gist_matrix(cases, problems)
    else:
        _shadow_matrix(cases, labels, problems)


def _check_passage_variety(passages: Passages, used: set[str], problems: list[str]) -> None:
    for passage in passages.passages:
        if passage.id not in used:
            problems.append(f"passage {passage.id} is in passages.json but not used by any case")
    chosen = [p for p in passages.passages if p.id in used]
    topics: dict[str, int] = defaultdict(int)
    accents: dict[str, int] = defaultdict(int)
    for passage in chosen:
        topics[passage.topic.strip().lower()] += 1
        accents[passage.speaker_accent.strip().lower()] += 1
    for topic, count in sorted(topics.items()):
        if count > 1:
            problems.append(f"topic {topic} is used by {count} passages; one passage per topic")
    if len(accents) < MIN_PASSAGE_ACCENTS:
        problems.append(
            f"{len(accents)} speaker accents in the passages; need {MIN_PASSAGE_ACCENTS}"
        )
    for accent, count in sorted(accents.items()):
        if count > MAX_PASSAGES_PER_ACCENT:
            problems.append(
                f"speaker accent {accent} is in more than {MAX_PASSAGES_PER_ACCENT} passages "
                f"({count})"
            )


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
    clean: dict[str, list[Any]] = defaultdict(list)
    for case in cases:
        if "kind:clean" in case.tags:
            for pair in _tags(case, "pair:"):
                clean[pair].append(case)
    for pair, versions in sorted(clean.items()):
        if len(versions) > 1:
            problems.append(f"pair {pair}: more than one clean version")
    for case in cases:
        if "at-12" not in case.tags:
            continue
        twins = [
            twin
            for pair in _tags(case, "pair:")
            for twin in clean.get(pair, [])
            if "at-12" not in twin.tags  # a case cannot be its own clean version
        ]
        if not twins:
            problems.append(
                f"{case.id}: at-12 case needs a pair: tag shared with a different kind:clean case"
            )
            continue
        twin = twins[0]
        if _tags(twin, "passage:") != _tags(case, "passage:"):
            problems.append(
                f"{case.id}: at-12 case and its clean version must use the same passage"
            )
        if twin.expected.level != case.expected.level:
            problems.append(f"{case.id}: at-12 case must have the same level as its clean version")


def _shadow_matrix(cases: Any, labels: WordLabels | None, problems: list[str]) -> None:
    speakers: dict[str, set[str]] = defaultdict(set)
    for case in cases:
        group, speaker = _tags(case, "accent:"), _tags(case, "speaker:")
        if len(group) == 1 and len(speaker) == 1:
            speakers[group[0]].add(speaker[0])
    strong = [g for g, s in speakers.items() if len(s) >= MIN_SPEAKERS_PER_GROUP]
    if len(strong) < MIN_ACCENT_GROUPS:
        problems.append(
            f"{len(strong)} accent groups with {MIN_SPEAKERS_PER_GROUP}+ speakers; "
            f"need {MIN_ACCENT_GROUPS} (groups: "
            + ", ".join(f"{g}={len(s)} speakers" for g, s in sorted(speakers.items()))
            + ")"
        )
    versions: dict[str, dict[str, list[Any]]] = defaultdict(lambda: defaultdict(list))
    for case in cases:
        deliveries = _tags(case, "delivery:")
        pairs = _tags(case, "pair:")
        if pairs and (len(deliveries) != 1 or deliveries[0] not in ("clear", "mumbled")):
            problems.append(f"{case.id}: a pair case needs one delivery: tag, clear or mumbled")
            continue
        for pair in pairs:
            versions[pair][deliveries[0]].append(case)
    valid = 0
    for pair, sides in sorted(versions.items()):
        if len(sides["clear"]) != 1 or len(sides["mumbled"]) != 1:
            problems.append(f"pair {pair}: at-17 needs exactly one clear and one mumbled case")
            continue
        clear, mumbled = sides["clear"][0], sides["mumbled"][0]
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
    _check_files(directory, problems)
    _check_templates(suite, directory, problems)
    dataset_path = directory / "dataset.json"
    if not dataset_path.exists():
        if require_complete:
            problems.append("dataset.json is missing: no real data has been collected yet")
        return problems
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
    by two teachers is one pair and a case graded by three is three; a case with more
    teachers therefore weighs more. Shadow grades also report how far each teacher's
    `overall` is from the product formula, the equal-weight mean of the six measures
    other than accent (FR-SH-9, FR-SH-15).
    """
    grades = TeacherGrades.model_validate_json(grades_path.read_text(encoding="utf-8"))
    by_case: dict[str, list[TeacherGrade]] = defaultdict(list)
    for entry in grades.grades:
        by_case[entry.case].append(entry)
    pairs = [pair for entries in by_case.values() for pair in combinations(entries, 2)]
    differences: dict[str, list[float]] = defaultdict(list)
    for a, b in pairs:
        for name in a.grade.scores.keys() & b.grade.scores.keys():
            differences[name].append(abs(a.grade.scores[name] - b.grade.scores[name]))
        differences["overall"].append(abs(a.grade.overall - b.grade.overall))
        if a.grade.filler_count is not None and b.grade.filler_count is not None:
            differences["filler_count"].append(abs(a.grade.filler_count - b.grade.filler_count))
    levels = [(a.grade.level, b.grade.level) for a, b in pairs if a.grade.level and b.grade.level]
    formula = [
        abs(e.grade.overall - mean(v for k, v in e.grade.scores.items() if k != "accent"))
        for e in grades.grades
        if e.grade.scores.keys() >= SHADOW_MEASURES
    ]
    return {
        "double_graded_cases": sum(len(entries) > 1 for entries in by_case.values()),
        "teacher_pairs": len(pairs),
        "level_agreement": mean(x == y for x, y in levels) if levels else None,
        "mean_abs_difference": {name: mean(values) for name, values in differences.items()},
        "overall_vs_six_measure_mean": mean(formula) if formula else None,
    }


def _report_agreement(suite: str, directory: Path) -> bool:
    """Print the agreement report; True when it could not be produced."""
    path = directory / "teacher-grades.json"
    if not path.exists():
        print(f"{suite}: teacher-grades.json is missing")
        return True
    try:
        print(f"{suite}: {json.dumps(agreement(path), indent=2)}")
    except (ValidationError, ValueError) as error:
        print(f"{suite}: teacher-grades.json: invalid ({str(error).splitlines()[0]})")
        return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--suite", choices=[*SUITES, "all"], default="all")
    parser.add_argument("--dir", type=Path, help="one suite's directory (needs --suite)")
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument("--agreement", action="store_true", help="report teacher agreement")
    args = parser.parse_args(argv)
    if args.dir and args.suite == "all":
        parser.error("--dir needs --suite")
    if args.agreement and args.require_complete:
        parser.error("--agreement reports agreement only; run --require-complete separately")
    root = Path(__file__).resolve().parents[3] / "ai-evals"
    suites = SUITES if args.suite == "all" else (args.suite,)
    failed = False
    for suite in suites:
        directory = args.dir or root / DIRECTORIES[suite]
        if args.agreement:
            failed |= _report_agreement(suite, directory)
            continue
        problems = check_suite(suite, directory, require_complete=args.require_complete)
        print(f"{suite}: {'ok' if not problems else f'{len(problems)} problem(s)'}")
        for problem in problems:
            print(f"  - {problem}")
        failed |= bool(problems)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
