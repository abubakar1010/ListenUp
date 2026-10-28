"""The #106/#107 collection kit: templates stay empty and the checker enforces the matrix.

Every grade, speaker and passage built here is invented test data in a temporary
directory; none of it is a teacher grade or learner data and none is committed.
"""

import copy
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).parents[5]
DIRECTORIES = {"gist": "gists", "shadow": "shadow"}
SCRIPT = Path(__file__).parents[3] / "scripts" / "check_golden_sets.py"
LEVELS = ("Needs work", "Fair", "Good", "Excellent")
GIST = {"main_idea": 50, "key_details": 50, "accuracy": 50}
SHADOW = dict.fromkeys(
    ("timing", "pronunciation", "accent", "articulation", "fluency", "fillers", "completeness"), 50
)
ACCENTS = ("british", "american", "indian", "australian", "nigerian")
KEY_POINTS = [
    {"id": "kp1", "text": "Main.", "kind": "main"},
    {"id": "kp2", "text": "Detail one.", "kind": "supporting"},
    {"id": "kp3", "text": "Detail two.", "kind": "supporting"},
]


def load_checker() -> Any:
    spec = importlib.util.spec_from_file_location("check_golden_sets", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = load_checker()


def write(directory: Path, name: str, data: object) -> None:
    (directory / name).write_text(json.dumps(data), encoding="utf-8")


def passages(prefix: str) -> dict:
    return {
        "version": 1,
        "passages": [
            {
                "id": f"{prefix}{n:02}",
                "title": f"Invented passage {n}",
                "topic": f"topic-{n}",
                "speaker_accent": ACCENTS[n % 5],
                "licence": "CC BY 4.0",
                "source_url": f"https://example.org/audio/{n}",
                "duration_seconds": 75,
            }
            for n in range(1, 11)
        ],
    }


def teacher_grades(case_ids: list[str], grade_for) -> dict:
    return {
        "version": 1,
        "dataset": "set",
        "grades": [{"case": c, "teacher": "T1", "grade": grade_for(c)} for c in case_ids],
    }


def gist_files() -> dict[str, dict]:
    cases = []
    for i in range(50):
        level = LEVELS[i % 4]
        passage = i % 10 + 1
        tags = [f"cefr:{('b1', 'b2', 'c1')[i % 3]}"]
        if i < 3:
            tags.append("at-10")
            level = ("Good", "Excellent", "Good")[i]
        elif i < 6:
            tags.append("at-11")
            level = "Needs work"
        elif i < 9:
            tags += ["at-12", f"pair:pr{i - 5}"]
            level = LEVELS[i % 4]
        elif i < 12:
            tags.append("at-13")
        elif i < 15:
            tags += ["kind:clean", f"pair:pr{i - 11}"]
            level = LEVELS[(i - 6) % 4]
            passage = (i - 6) % 10 + 1  # the clean version uses its at-12 twin's passage
        cases.append(
            {
                "id": f"g{i:02}",
                "tags": [f"passage:p{passage:02}", *tags],
                "input": {
                    "transcript": "A passage.",
                    "gist": "A gist.",
                    "key_points": copy.deepcopy(KEY_POINTS),
                },
                "expected": {"scores": GIST, "overall": 50, "level": level},
            }
        )
    levels = {c["id"]: c["expected"]["level"] for c in cases}
    at_11 = {c["id"] for c in cases if "at-11" in c["tags"]}
    dataset = {
        "version": 1,
        "id": "set",
        "kind": "teacher",
        "suite": "gist",
        "source": "Invented test set",
        "cases": cases,
    }
    grades = {
        "version": 1,
        "dataset": "set",
        "grades": [
            {
                "case": c["id"],
                "teacher": "T1",
                "grade": {"scores": GIST, "overall": 50, "level": levels[c["id"]]},
                "covered_points": [] if c["id"] in at_11 else ["kp1", "kp2"],
            }
            for c in cases
        ],
    }
    return {"dataset.json": dataset, "teacher-grades.json": grades, "passages.json": passages("p")}


def shadow_files() -> dict[str, dict]:
    cases, labels = [], []
    for i in range(50):
        group = i % 5
        passage = f"s{i % 10 + 1:02}"
        tags = [f"accent:group-{group}", f"speaker:s{group}{(i // 5) % 4}"]
        overall = 60
        if i < 6:
            passage = f"s{i // 2 + 1:02}"
            tags += [f"pair:pr{i // 2 + 1}", "at-17"]
            tags.append("delivery:clear" if i % 2 == 0 else "delivery:mumbled")
            overall = 80 if i % 2 == 0 else 40
        tags.append(f"passage:{passage}")
        cases.append(
            {
                "id": f"r{i:02}",
                "tags": tags,
                "context": {"audio_seconds": 75},
                "input": {
                    "recording": f"external/rec-{i:02}.wav",
                    "reference_audio": f"external/ref-{passage}.wav",
                    "reference_text": "Reference text.",
                },
                "expected": {"scores": SHADOW, "overall": overall, "filler_count": i % 3},
            }
        )
        labels.append(
            {
                "case": f"r{i:02}",
                "words": [
                    {"word": "reference", "label": "good"},
                    {"word": "text.", "label": "good"},
                ],
            }
        )
    ids = [c["id"] for c in cases]
    overall = {c["id"]: c["expected"]["overall"] for c in cases}
    dataset = {
        "version": 1,
        "id": "set",
        "kind": "teacher",
        "suite": "shadow",
        "source": "Invented test set",
        "cases": cases,
    }
    grades = teacher_grades(
        ids,
        lambda c: {"scores": SHADOW, "overall": overall[c], "filler_count": int(c[1:]) % 3},
    )
    return {
        "dataset.json": dataset,
        "teacher-grades.json": grades,
        "passages.json": passages("s"),
        "word-labels.json": {"version": 1, "labels": labels},
    }


def put(tmp_path: Path, files: dict[str, dict]) -> Path:
    for name, data in files.items():
        write(tmp_path, name, data)
    return tmp_path


def second_teacher(files: dict[str, dict], case: str, code: str, **changes: Any) -> dict:
    grades = files["teacher-grades.json"]["grades"]
    entry = copy.deepcopy(next(g for g in grades if g["case"] == case))
    entry["teacher"] = code
    for key, value in changes.items():
        if key in ("overall", "level", "filler_count"):
            entry["grade"][key] = value
        else:
            entry["grade"]["scores"][key] = value
    grades.append(entry)
    return entry


@pytest.mark.parametrize("suite", ["gist", "shadow"])
def test_committed_templates_are_valid_and_hold_no_data(suite):
    directory = ROOT / "ai-evals" / DIRECTORIES[suite]
    assert checker.check_suite(suite, directory) == []
    template = json.loads((directory / "dataset.template.json").read_text())
    assert template["cases"] == [] and template["kind"] == "teacher"
    for name in directory.glob("*.template.json"):
        data = json.loads(name.read_text())
        assert not any(data.get(k) for k in ("cases", "grades", "passages", "labels")), name


@pytest.mark.parametrize("suite", ["gist", "shadow"])
def test_complete_mode_refuses_while_no_real_data_is_committed(suite):
    directory = ROOT / "ai-evals" / DIRECTORIES[suite]
    problems = checker.check_suite(suite, directory, require_complete=True)
    assert any("dataset.json is missing" in p for p in problems)


@pytest.mark.parametrize(
    ("suite", "files"), [("gist", gist_files), ("shadow", shadow_files)], ids=["gist", "shadow"]
)
def test_a_set_that_meets_the_matrix_passes_complete_mode(tmp_path, suite, files):
    put(tmp_path, files())
    assert checker.check_suite(suite, tmp_path, require_complete=True) == []


def test_incomplete_sets_pass_only_when_completeness_is_not_required(tmp_path):
    files = gist_files()
    files["dataset.json"]["cases"] = files["dataset.json"]["cases"][:20]
    files["teacher-grades.json"]["grades"] = files["teacher-grades.json"]["grades"][:20]
    put(tmp_path, files)
    assert checker.check_suite("gist", tmp_path) == []
    assert checker.check_suite("gist", tmp_path, require_complete=True)


def mutate_template(name: str, data: Any) -> Any:
    if name == "cases":
        data["cases"] = [{"id": "g01"}]
    elif name == "suite":
        data["suite"] = "shadow"
    elif name == "kind":
        data["kind"] = "synthetic"
    elif name == "note":
        data["note"] = "graded by someone"
    elif name == "email":
        data["source"] = "ask mrs.rahman@school.org"
    elif name == "list":
        data = []
    return data


@pytest.mark.parametrize(
    ("name", "fragment"),
    [
        ("cases", "empty"),
        ("suite", "dataset.template.json"),
        ("kind", "dataset.template.json"),
        ("note", "unexpected"),
        ("email", "personal data"),
        ("list", "object"),
    ],
)
def test_template_rules_reject_data_and_odd_shapes(tmp_path, name, fragment):
    directory = ROOT / "ai-evals" / "gists"
    for path in directory.glob("*.template.json"):
        data = json.loads(path.read_text())
        if path.name == "dataset.template.json":
            data = mutate_template(name, data)
        write(tmp_path, path.name, data)
    problems = checker.check_suite("gist", tmp_path)
    assert any(fragment in p for p in problems), problems


def test_a_template_that_is_not_json_is_reported(tmp_path):
    (tmp_path / "dataset.template.json").write_text("{not json")
    assert any("not valid JSON" in p for p in checker.check_suite("gist", tmp_path))


def test_unknown_template_file_is_reported(tmp_path):
    write(tmp_path, "notes.template.json", {"version": 1})
    assert any("unknown template" in p for p in checker.check_suite("gist", tmp_path))


@pytest.mark.parametrize("name", ["rec-01.wav", "teacher-voice.mp3"])
def test_audio_files_cannot_enter_a_suite_directory(tmp_path, name):
    put(tmp_path, gist_files())
    (tmp_path / name).write_bytes(b"RIFF")
    assert any("outside the repository" in p for p in checker.check_suite("gist", tmp_path))


def test_an_external_folder_cannot_enter_a_suite_directory(tmp_path):
    put(tmp_path, shadow_files())
    (tmp_path / "external").mkdir()
    (tmp_path / "external" / "rec-01.txt").write_text("x")
    assert any("outside the repository" in p for p in checker.check_suite("shadow", tmp_path))


@pytest.mark.parametrize("missing", ["teacher-grades.json", "passages.json"])
def test_complete_mode_needs_every_sidecar(tmp_path, missing):
    put(tmp_path, gist_files())
    (tmp_path / missing).unlink()
    problems = checker.check_suite("gist", tmp_path, require_complete=True)
    assert [p for p in problems if f"{missing} is missing" in p] == [f"{missing} is missing"]


def gist_mutation(name):
    def mutate(files):
        cases = files["dataset.json"]["cases"]
        grades = files["teacher-grades.json"]["grades"]
        if name == "no-excellent":
            for c in cases:
                if c["expected"]["level"] == "Excellent":
                    c["expected"]["level"] = "Good"
            for g in grades:
                if g["grade"]["level"] == "Excellent":
                    g["grade"]["level"] = "Good"
        elif name == "no-at-13":
            for c in cases:
                c["tags"] = [t for t in c["tags"] if t != "at-13"]
        elif name == "few-passages":
            for c in cases:
                c["tags"] = [
                    f"passage:p0{n % 5 + 1}" if t.startswith("passage:") else t
                    for n, t in enumerate(c["tags"])
                ]
        elif name == "no-c1":
            for c in cases:
                c["tags"] = ["cefr:b1" if t == "cefr:c1" else t for t in c["tags"]]
        elif name == "weak-at-10":
            cases[0]["expected"]["level"] = "Fair"
            grades[0]["grade"]["level"] = "Fair"
        elif name == "at-12-level-differs":
            cases[6]["expected"]["level"] = "Needs work"
            grades[6]["grade"]["level"] = "Needs work"
            cases[12]["expected"]["level"] = "Excellent"
            grades[12]["grade"]["level"] = "Excellent"
        elif name == "at-11-graded-fair":
            cases[3]["expected"]["level"] = "Fair"
            grades[3]["grade"]["level"] = "Fair"
        elif name == "at-12-unpaired":
            cases[14]["tags"] = [t for t in cases[14]["tags"] if t != "kind:clean"]
        elif name == "at-12-own-twin":
            for i in (6, 7, 8):
                cases[i]["tags"].append("kind:clean")
            for i in (12, 13, 14):
                cases[i]["tags"] = [t for t in cases[i]["tags"] if t != "kind:clean"]
        elif name == "at-12-other-passage":
            cases[12]["tags"] = [
                "passage:p10" if t.startswith("passage:") else t for t in cases[12]["tags"]
            ]
        elif name == "two-clean-versions":
            cases[13]["tags"] = [
                "pair:pr1" if t.startswith("pair:") else t for t in cases[13]["tags"]
            ]
        elif name == "email":
            cases[0]["input"]["gist"] = "mail me at learner@example.com"
        elif name == "signed-url":
            cases[0]["input"]["transcript"] = "https://bucket.s3.example/x?X-Amz-Signature=abc"
        elif name == "unknown-passage":
            cases[0]["tags"] = ["passage:p99"]
        elif name == "ungraded-case":
            grades.pop()
        elif name == "unknown-case-grade":
            grades.append({**copy.deepcopy(grades[0]), "case": "g99"})
        elif name == "teacher-named":
            grades[0]["teacher"] = "Mrs Rahman"
        elif name == "synthetic-kind":
            files["dataset.json"]["kind"] = "synthetic"
        elif name == "too-few-cases":
            files["dataset.json"]["cases"] = cases[:40]
            grades[:] = grades[:40]
        elif name == "too-many-cases":
            for i in range(50, 60):
                extra = copy.deepcopy(cases[i - 50])
                extra["id"] = f"g{i}"
                cases.append(extra)
                grades.append({**copy.deepcopy(grades[i - 50]), "case": f"g{i}"})
        elif name == "unused-passage":
            files["passages.json"]["passages"].append(
                {**files["passages.json"]["passages"][0], "id": "p11", "topic": "topic-11"}
            )
        elif name == "shared-topic":
            files["passages.json"]["passages"][1]["topic"] = "topic-1"
        elif name == "duplicate-passage-id":
            files["passages.json"]["passages"][1]["id"] = "p01"
        elif name == "one-accent":
            for p in files["passages.json"]["passages"]:
                p["speaker_accent"] = "british"
        elif name == "accent-in-many-passages":
            for p in files["passages.json"]["passages"][1:5]:
                p["speaker_accent"] = files["passages.json"]["passages"][0]["speaker_accent"]
        elif name == "two-passage-tags":
            cases[0]["tags"].append("passage:p02")
        elif name == "empty-pair-tag":
            cases[0]["tags"].append("pair:")
        elif name == "duplicate-tag":
            cases[0]["tags"].append("cefr:b1" if "cefr:b1" in cases[0]["tags"] else "cefr:b2")
        elif name == "uppercase-tag":
            cases[0]["tags"].append("At-10")
        elif name == "bad-case-id":
            cases[0]["id"] = "learner-jane"
            grades[0]["case"] = "learner-jane"
        elif name == "no-main-point":
            for case in cases:
                for point in case["input"]["key_points"]:
                    point["kind"] = "supporting"
        elif name == "two-main-points":
            cases[0]["input"]["key_points"][1]["kind"] = "main"
        elif name == "two-key-points":
            del cases[0]["input"]["key_points"][2]
        elif name == "key-point-order":
            cases[0]["input"]["key_points"][1]["id"] = "kp3"
            cases[0]["input"]["key_points"][2]["id"] = "kp2"
        elif name == "key-points-differ-within-passage":
            cases[0]["input"]["key_points"][1]["text"] = "Another detail."
        elif name == "transcript-differs-within-passage":
            cases[0]["input"]["transcript"] = "Another transcript."
        elif name == "teacher-score-keys":
            grades[0]["grade"]["scores"] = {"foo": 1}
        elif name == "teacher-level-missing":
            del grades[0]["grade"]["level"]
        elif name == "duplicate-teacher-entry":
            grades.append(copy.deepcopy(grades[20]))
        elif name == "expected-differs-from-only-teacher":
            grades[20]["grade"]["overall"] = 99
        elif name == "at-11-covers-main-idea":
            grades[3]["covered_points"] = ["kp1"]
        elif name == "unknown-covered-point":
            grades[0]["covered_points"] = ["kp9"]
        elif name == "grades-for-another-dataset":
            files["teacher-grades.json"]["dataset"] = "other"

    return mutate


@pytest.mark.parametrize(
    ("name", "fragment"),
    [
        ("no-excellent", "Excellent"),
        ("no-at-13", "at-13"),
        ("few-passages", "passages in use"),
        ("no-c1", "cefr:c1"),
        ("weak-at-10", "at-10"),
        ("at-12-level-differs", "at-12"),
        ("at-11-graded-fair", "at-11 case must be graded"),
        ("at-12-unpaired", "at-12"),
        ("at-12-own-twin", "at-12"),
        ("at-12-other-passage", "same passage"),
        ("two-clean-versions", "more than one clean"),
        ("email", "personal data"),
        ("signed-url", "personal data"),
        ("unknown-passage", "passages.json"),
        ("ungraded-case", "no teacher grade"),
        ("unknown-case-grade", "unknown case"),
        ("teacher-named", "teacher"),
        ("synthetic-kind", "teacher"),
        ("too-few-cases", "about 50"),
        ("too-many-cases", "about 50"),
        ("unused-passage", "not used"),
        ("shared-topic", "topic"),
        ("duplicate-passage-id", "duplicate passage"),
        ("one-accent", "speaker accents"),
        ("accent-in-many-passages", "more than 3 passages"),
        ("two-passage-tags", "passage: tag"),
        ("empty-pair-tag", "invalid tag"),
        ("duplicate-tag", "duplicate tag"),
        ("uppercase-tag", "invalid tag"),
        ("bad-case-id", "case id"),
        ("no-main-point", "main"),
        ("two-main-points", "main"),
        ("two-key-points", "3 to 6 key points"),
        ("key-point-order", "kp1"),
        ("key-points-differ-within-passage", "disagree"),
        ("transcript-differs-within-passage", "disagree"),
        ("teacher-score-keys", "scores must be exactly"),
        ("teacher-level-missing", "needs a level"),
        ("duplicate-teacher-entry", "duplicate grade"),
        ("expected-differs-from-only-teacher", "expected differs"),
        ("at-11-covers-main-idea", "at-11"),
        ("unknown-covered-point", "covered_points"),
        ("grades-for-another-dataset", "another dataset"),
    ],
)
def test_gist_coverage_and_privacy_rules(tmp_path, name, fragment):
    files = gist_files()
    gist_mutation(name)(files)
    put(tmp_path, files)
    problems = checker.check_suite("gist", tmp_path, require_complete=True)
    assert any(fragment in p for p in problems), problems


def test_expected_may_be_the_agreed_grade_when_two_teachers_graded(tmp_path):
    files = gist_files()
    second_teacher(files, "g20", "T2", main_idea=70, overall=60)
    expected = files["dataset.json"]["cases"][20]["expected"]
    expected["scores"] = {**GIST, "main_idea": 70}  # the agreed grade is the second teacher's
    expected["overall"] = 60
    put(tmp_path, files)
    assert checker.check_suite("gist", tmp_path, require_complete=True) == []


@pytest.mark.parametrize(
    ("text", "flagged"),
    [
        ("call 07911 123456", True),
        ("call +44 7911 123456", True),
        ("call 0171-1234567", True),
        ("call (555) 123-4567", True),
        ("call me on 555.123.4567", True),
        ("we met on 2024-01-15 at 10", False),
        ("it costs 1 000 000 000 dollars", False),
        ("she was born in 1990 01 15 12", False),
        ("reference 12345678901234", False),
        ("about 12 percent of 300", False),
        ("see https://example.org/audio/0712345678901", False),
        ("file ref-0712345678901 attached", False),
    ],
)
def test_phone_numbers_are_found_and_ordinary_numbers_are_not(tmp_path, text, flagged):
    files = gist_files()
    files["dataset.json"]["cases"][0]["input"]["gist"] = text
    put(tmp_path, files)
    problems = checker.check_suite("gist", tmp_path)
    assert any("personal data" in p for p in problems) is flagged, problems


def test_a_long_number_in_a_public_source_url_is_not_personal_data(tmp_path):
    files = gist_files()
    files["passages.json"]["passages"][0]["source_url"] = "https://archive.org/details/t-1234567890"
    put(tmp_path, files)
    assert checker.check_suite("gist", tmp_path, require_complete=True) == []


def shadow_mutation(name):
    def mutate(files):
        cases = files["dataset.json"]["cases"]
        if name == "three-accents":
            for c in cases:
                c["tags"] = [
                    "accent:group-0" if t in ("accent:group-3", "accent:group-4") else t
                    for t in c["tags"]
                ]
        elif name == "thin-group":
            for c in cases:
                if {"accent:group-3", "accent:group-4"} & set(c["tags"]):
                    c["tags"] = [
                        "speaker:s90" if t.startswith("speaker:") else t for t in c["tags"]
                    ]
        elif name == "no-pairs":
            for c in cases:
                c["tags"] = [t for t in c["tags"] if t != "delivery:mumbled"]
        elif name == "mumbled-not-lower":
            cases[1]["expected"]["overall"] = 90
        elif name == "pair-on-two-passages":
            cases[1]["tags"] = [
                "passage:s09" if t.startswith("passage:") else t for t in cases[1]["tags"]
            ]
        elif name == "two-clear-versions":
            cases[6]["tags"] += ["pair:pr1", "delivery:clear"]
        elif name == "both-deliveries":
            cases[0]["tags"].append("delivery:mumbled")
        elif name == "absolute-path":
            cases[0]["input"]["recording"] = "/home/learner/rec.wav"
        elif name == "url-audio":
            cases[0]["input"]["recording"] = "https://example.org/rec.wav"
        elif name == "dotdot-path":
            cases[0]["input"]["recording"] = "external/../rec-01.wav"
        elif name == "drive-path":
            cases[0]["input"]["recording"] = "external/C:/rec-01.wav"
        elif name == "double-slash-path":
            cases[0]["input"]["recording"] = "external//rec-01.wav"
        elif name == "named-file":
            cases[0]["input"]["recording"] = "external/jane-doe-recording.wav"
        elif name == "named-reference-file":
            cases[0]["input"]["reference_audio"] = "external/jane-doe.wav"
        elif name == "bad-duration":
            cases[0]["context"]["audio_seconds"] = 120
        elif name == "duration-not-set":
            del cases[0]["context"]["audio_seconds"]
        elif name == "duration-differs-from-segment":
            cases[0]["context"]["audio_seconds"] = 80
        elif name == "segment-too-long":
            files["passages.json"]["passages"][0]["duration_seconds"] = 500
        elif name == "no-fillers":
            for c in cases:
                c["expected"]["filler_count"] = 0
            for g in files["teacher-grades.json"]["grades"]:
                g["grade"]["filler_count"] = 0
        elif name == "all-fillers":
            for c in cases:
                c["expected"]["filler_count"] = 2
            for g in files["teacher-grades.json"]["grades"]:
                g["grade"]["filler_count"] = 2
        elif name == "missing-labels":
            files["word-labels.json"]["labels"].pop()
        elif name == "bad-label":
            files["word-labels.json"]["labels"][0]["words"][0]["label"] = "great"
        elif name == "labels-for-unknown-case":
            files["word-labels.json"]["labels"].append(
                {"case": "r99", "words": [{"word": "x", "label": "good"}]}
            )
        elif name == "duplicate-labels":
            files["word-labels.json"]["labels"].append(files["word-labels.json"]["labels"][0])
        elif name == "labels-differ-from-reference-text":
            files["word-labels.json"]["labels"][0]["words"][0]["word"] = "totally"
        elif name == "no-speaker":
            cases[0]["tags"] = [t for t in cases[0]["tags"] if not t.startswith("speaker:")]
        elif name == "speaker-named":
            cases[0]["tags"] = [
                "speaker:jane-doe" if t.startswith("speaker:") else t for t in cases[0]["tags"]
            ]
        elif name == "speaker-in-two-groups":
            for c in cases:
                c["tags"] = [
                    f"speaker:s{t[-1]}" if t.startswith("speaker:") else t for t in c["tags"]
                ]
        elif name == "two-accent-tags":
            cases[0]["tags"].append("accent:group-1")
        elif name == "teacher-filler-count-missing":
            del files["teacher-grades.json"]["grades"][0]["grade"]["filler_count"]
        elif name == "teacher-covers-points":
            files["teacher-grades.json"]["grades"][0]["covered_points"] = ["kp1"]

    return mutate


SHADOW_RULES = [
    ("three-accents", "accent groups"),
    ("thin-group", "speakers"),
    ("no-pairs", "pairs, need"),
    ("mumbled-not-lower", "must score lower"),
    ("pair-on-two-passages", "same passage"),
    ("two-clear-versions", "exactly one clear"),
    ("both-deliveries", "one delivery"),
    ("absolute-path", "external/"),
    ("url-audio", "external/"),
    ("dotdot-path", "external/"),
    ("drive-path", "external/"),
    ("double-slash-path", "external/"),
    ("named-file", "external/"),
    ("named-reference-file", "external/"),
    ("bad-duration", "audio_seconds"),
    ("duration-not-set", "audio_seconds"),
    ("duration-differs-from-segment", "segment duration"),
    ("segment-too-long", "FR-SH-1"),
    ("no-fillers", "filler"),
    ("all-fillers", "filler"),
    ("missing-labels", "word labels"),
    ("bad-label", "word-labels.json"),
    ("labels-for-unknown-case", "unknown case"),
    ("duplicate-labels", "duplicate word labels"),
    ("labels-differ-from-reference-text", "do not match"),
    ("no-speaker", "speaker"),
    ("speaker-named", "speaker"),
    ("speaker-in-two-groups", "more than one accent group"),
    ("two-accent-tags", "accent"),
    ("teacher-filler-count-missing", "filler_count"),
    ("teacher-covers-points", "covered_points"),
]


@pytest.mark.parametrize(("name", "fragment"), SHADOW_RULES)
def test_shadow_coverage_and_privacy_rules(tmp_path, name, fragment):
    files = shadow_files()
    shadow_mutation(name)(files)
    put(tmp_path, files)
    problems = checker.check_suite("shadow", tmp_path, require_complete=True)
    assert any(fragment in p for p in problems), problems


@pytest.mark.parametrize(
    "name",
    [
        "absolute-path",
        "url-audio",
        "dotdot-path",
        "drive-path",
        "double-slash-path",
        "named-file",
        "speaker-named",
        "speaker-in-two-groups",
        "bad-label",
        "labels-for-unknown-case",
        "duplicate-labels",
        "labels-differ-from-reference-text",
        "bad-duration",
        "segment-too-long",
        "teacher-filler-count-missing",
    ],
)
def test_shadow_privacy_and_format_rules_apply_without_complete_mode(tmp_path, name):
    files = shadow_files()
    shadow_mutation(name)(files)
    put(tmp_path, files)
    assert checker.check_suite("shadow", tmp_path), name


def test_agreement_is_reported_only_for_cases_with_two_teachers(tmp_path):
    files = gist_files()
    first = second_teacher(files, "g00", "T2", main_idea=60, accuracy=40, overall=54, level="Fair")
    first["grade"]["level"] = (
        "Fair" if files["dataset.json"]["cases"][0]["expected"]["level"] != "Fair" else "Good"
    )
    put(tmp_path, files)

    report = checker.agreement(tmp_path / "teacher-grades.json")

    assert report["double_graded_cases"] == 1
    assert report["level_agreement"] == 0
    assert report["mean_abs_difference"]["main_idea"] == 10
    assert report["mean_abs_difference"]["accuracy"] == 10
    assert report["mean_abs_difference"]["overall"] == 4


def test_agreement_with_one_teacher_per_case_reports_nothing(tmp_path):
    put(tmp_path, gist_files())
    report = checker.agreement(tmp_path / "teacher-grades.json")
    assert report["double_graded_cases"] == 0
    assert report["level_agreement"] is None


def test_agreement_with_three_teachers_compares_every_pair(tmp_path):
    files = gist_files()
    level = files["dataset.json"]["cases"][20]["expected"]["level"]
    other = "Excellent" if level != "Excellent" else "Fair"
    second_teacher(files, "g20", "T2", main_idea=60, level=level)
    second_teacher(files, "g20", "T3", main_idea=80, level=other)
    put(tmp_path, files)

    report = checker.agreement(tmp_path / "teacher-grades.json")

    assert report["double_graded_cases"] == 1
    assert report["teacher_pairs"] == 3
    assert report["level_agreement"] == pytest.approx(1 / 3)
    assert report["mean_abs_difference"]["main_idea"] == pytest.approx((10 + 30 + 20) / 3)


def test_agreement_skips_pairs_where_a_level_is_missing(tmp_path):
    files = gist_files()
    entry = second_teacher(files, "g20", "T2", main_idea=60)
    del entry["grade"]["level"]
    put(tmp_path, files)
    report = checker.agreement(tmp_path / "teacher-grades.json")
    assert report["teacher_pairs"] == 1 and report["level_agreement"] is None


def test_shadow_agreement_includes_filler_counts_and_the_overall_formula(tmp_path):
    files = shadow_files()
    second_teacher(files, "r10", "T2", filler_count=4, accent=0)
    put(tmp_path, files)

    report = checker.agreement(tmp_path / "teacher-grades.json")

    assert report["mean_abs_difference"]["filler_count"] == 3  # r10 has 10 % 3 = 1 filler
    assert report["mean_abs_difference"]["accent"] == 50
    # every invented measure is 50; the overalls 80 (x3), 40 (x3) and 60 (x45) are off by 30, 10, 10
    assert report["overall_vs_six_measure_mean"] == pytest.approx((3 * 30 + 3 * 10 + 45 * 10) / 51)


def test_the_overall_formula_leaves_accent_out(tmp_path):
    files = shadow_files()
    for grade in files["teacher-grades.json"]["grades"]:
        grade["grade"]["scores"]["accent"] = 0
        grade["grade"]["overall"] = 50
    put(tmp_path, files)
    report = checker.agreement(tmp_path / "teacher-grades.json")
    assert report["overall_vs_six_measure_mean"] == 0


def test_agreement_does_not_crash_when_teachers_graded_different_dimensions(tmp_path):
    files = gist_files()
    entry = second_teacher(files, "g20", "T2")
    del entry["grade"]["scores"]["accuracy"]
    put(tmp_path, files)
    report = checker.agreement(tmp_path / "teacher-grades.json")
    assert "accuracy" not in report["mean_abs_difference"]


def test_main_exit_codes(tmp_path, capsys):
    put(tmp_path, gist_files())
    assert checker.main(["--suite", "gist", "--dir", str(tmp_path)]) == 0
    empty = tmp_path / "empty"
    empty.mkdir()
    assert checker.main(["--suite", "gist", "--dir", str(empty), "--require-complete"]) == 1
    assert "dataset.json is missing" in capsys.readouterr().out


def test_agreement_command_reports_json_and_fails_on_missing_or_invalid_grades(tmp_path, capsys):
    put(tmp_path, gist_files())
    assert checker.main(["--suite", "gist", "--dir", str(tmp_path), "--agreement"]) == 0
    assert '"teacher_pairs": 0' in capsys.readouterr().out
    (tmp_path / "teacher-grades.json").write_text("{}")
    assert checker.main(["--suite", "gist", "--dir", str(tmp_path), "--agreement"]) == 1
    assert "invalid" in capsys.readouterr().out
    (tmp_path / "teacher-grades.json").unlink()
    assert checker.main(["--suite", "gist", "--dir", str(tmp_path), "--agreement"]) == 1
    assert "teacher-grades.json" in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv",
    [["--dir", "somewhere"], ["--suite", "gist", "--agreement", "--require-complete"]],
)
def test_conflicting_options_are_a_usage_error(argv):
    with pytest.raises(SystemExit) as stopped:
        checker.main(argv)
    assert stopped.value.code == 2
