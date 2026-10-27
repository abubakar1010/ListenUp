"""The #106/#107 collection kit: templates stay empty and the checker enforces the matrix.

Every grade, speaker and passage built here is invented test data in a temporary
directory; none of it is a teacher grade or learner data and none is committed.
"""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[5]
DIRECTORIES = {"gist": "gists", "shadow": "shadow"}
SCRIPT = Path(__file__).parents[3] / "scripts" / "check_golden_sets.py"
LEVELS = ("Needs work", "Fair", "Good", "Excellent")
GIST = {"main_idea": 50, "key_details": 50, "accuracy": 50}
SHADOW = dict.fromkeys(
    ("timing", "pronunciation", "accent", "articulation", "fluency", "fillers", "completeness"), 50
)


def load_checker():
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
                "speaker_accent": "invented-accent",
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
        tags = [f"passage:p{i % 10 + 1:02}", f"cefr:{('b1', 'b2', 'c1')[i % 3]}"]
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
        cases.append(
            {
                "id": f"g{i:02}",
                "tags": tags,
                "input": {
                    "transcript": "A passage.",
                    "gist": "A gist.",
                    "key_points": [
                        {"id": "kp1", "text": "Main.", "kind": "main"},
                        {"id": "kp2", "text": "Detail.", "kind": "supporting"},
                    ],
                },
                "expected": {"scores": GIST, "overall": 50, "level": level},
            }
        )
    ids = [c["id"] for c in cases]
    levels = {c["id"]: c["expected"]["level"] for c in cases}
    dataset = {
        "version": 1,
        "id": "set",
        "kind": "teacher",
        "suite": "gist",
        "source": "Invented test set",
        "cases": cases,
    }
    grades = teacher_grades(ids, lambda c: {"scores": GIST, "overall": 50, "level": levels[c]})
    return {"dataset.json": dataset, "teacher-grades.json": grades, "passages.json": passages("p")}


def shadow_files() -> dict[str, dict]:
    cases, labels = [], []
    for i in range(50):
        group = i % 5
        passage = f"s{i % 10 + 1:02}"
        tags = [f"accent:group-{group}", f"speaker:spk-{group}-{(i // 5) % 4}"]
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
        labels.append({"case": f"r{i:02}", "words": [{"word": "hello", "label": "good"}]})
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


def gist_mutation(name):
    def mutate(files):
        cases = files["dataset.json"]["cases"]
        if name == "no-excellent":
            for c in cases:
                if c["expected"]["level"] == "Excellent":
                    c["expected"]["level"] = "Good"
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
        elif name == "at-12-level-differs":
            cases[6]["expected"]["level"] = "Needs work"
            cases[12]["expected"]["level"] = "Excellent"
        elif name == "at-12-unpaired":
            cases[14]["tags"] = [t for t in cases[14]["tags"] if t != "kind:clean"]
        elif name == "email":
            cases[0]["input"]["gist"] = "mail me at learner@example.com"
        elif name == "signed-url":
            cases[0]["input"]["transcript"] = "https://bucket.s3.example/x?X-Amz-Signature=abc"
        elif name == "unknown-passage":
            cases[0]["tags"] = ["passage:p99"]
        elif name == "ungraded-case":
            files["teacher-grades.json"]["grades"].pop()
        elif name == "teacher-named":
            files["teacher-grades.json"]["grades"][0]["teacher"] = "Mrs Rahman"
        elif name == "synthetic-kind":
            files["dataset.json"]["kind"] = "synthetic"

    return mutate


@pytest.mark.parametrize(
    ("name", "fragment"),
    [
        ("no-excellent", "Excellent"),
        ("no-at-13", "at-13"),
        ("few-passages", "passages"),
        ("no-c1", "cefr:c1"),
        ("weak-at-10", "at-10"),
        ("at-12-level-differs", "at-12"),
        ("at-12-unpaired", "at-12"),
        ("email", "personal data"),
        ("signed-url", "personal data"),
        ("unknown-passage", "passages.json"),
        ("ungraded-case", "no teacher grade"),
        ("teacher-named", "teacher"),
        ("synthetic-kind", "teacher"),
    ],
)
def test_gist_coverage_and_privacy_rules(tmp_path, name, fragment):
    files = gist_files()
    gist_mutation(name)(files)
    put(tmp_path, files)
    problems = checker.check_suite("gist", tmp_path, require_complete=True)
    assert any(fragment in p for p in problems), problems


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
                        "speaker:spk-x-0" if t.startswith("speaker:") else t for t in c["tags"]
                    ]
        elif name == "no-pairs":
            for c in cases:
                c["tags"] = [t for t in c["tags"] if t != "delivery:mumbled"]
        elif name == "mumbled-not-lower":
            cases[1]["expected"]["overall"] = 90
        elif name == "absolute-path":
            cases[0]["input"]["recording"] = "/home/learner/rec.wav"
        elif name == "url-audio":
            cases[0]["input"]["recording"] = "https://example.org/rec.wav"
        elif name == "bad-duration":
            cases[0]["context"]["audio_seconds"] = 120
        elif name == "no-fillers":
            for c in cases:
                c["expected"]["filler_count"] = 0
        elif name == "missing-labels":
            files["word-labels.json"]["labels"].pop()
        elif name == "bad-label":
            files["word-labels.json"]["labels"][0]["words"][0]["label"] = "great"
        elif name == "no-speaker":
            cases[0]["tags"] = [t for t in cases[0]["tags"] if not t.startswith("speaker:")]

    return mutate


@pytest.mark.parametrize(
    ("name", "fragment"),
    [
        ("three-accents", "accent groups"),
        ("thin-group", "speakers"),
        ("no-pairs", "at-17"),
        ("mumbled-not-lower", "at-17"),
        ("absolute-path", "external/"),
        ("url-audio", "external/"),
        ("bad-duration", "audio_seconds"),
        ("no-fillers", "filler"),
        ("missing-labels", "word labels"),
        ("bad-label", "word-labels.json"),
        ("no-speaker", "speaker"),
    ],
)
def test_shadow_coverage_and_privacy_rules(tmp_path, name, fragment):
    files = shadow_files()
    shadow_mutation(name)(files)
    put(tmp_path, files)
    problems = checker.check_suite("shadow", tmp_path, require_complete=True)
    assert any(fragment in p for p in problems), problems


def test_agreement_is_reported_only_for_cases_with_two_teachers(tmp_path):
    files = gist_files()
    grades = files["teacher-grades.json"]["grades"]
    first = copy.deepcopy(grades[0])
    first["teacher"] = "T2"
    first["grade"]["scores"] = {"main_idea": 60, "key_details": 50, "accuracy": 40}
    first["grade"]["overall"] = 54
    first["grade"]["level"] = "Fair" if grades[0]["grade"]["level"] != "Fair" else "Good"
    grades.append(first)
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


def test_main_exit_codes(tmp_path, capsys):
    put(tmp_path, gist_files())
    assert checker.main(["--suite", "gist", "--dir", str(tmp_path)]) == 0
    empty = tmp_path / "empty"
    empty.mkdir()
    assert checker.main(["--suite", "gist", "--dir", str(empty), "--require-complete"]) == 1
    assert "dataset.json is missing" in capsys.readouterr().out
