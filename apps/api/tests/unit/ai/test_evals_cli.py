import json
from pathlib import Path

import pytest

from listenup.ai.evals.cli import main

ROOT = Path(__file__).resolve().parents[5]


@pytest.fixture(autouse=True)
def cli_accounting(monkeypatch, fake_accounting):
    monkeypatch.setattr("listenup.ai.evals.cli.PostgresAccounting", lambda _: fake_accounting)


def args(tmp_path, suite="gist"):
    return [
        "--dataset",
        str(ROOT / f"ai-evals/fixtures/{suite}.json"),
        "--thresholds",
        str(ROOT / "ai-evals/smoke.thresholds.json"),
        "--ai-config",
        str(ROOT / "apps/api/src/listenup/ai/ai.fake.yaml"),
        "--report",
        str(tmp_path / "report.json"),
        "--offline",
        "--smoke",
    ]


@pytest.mark.parametrize("suite", ["gist", "shadow"])
def test_cli_reports_each_suite(tmp_path, suite):
    assert main(args(tmp_path, suite)) == 0
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["status"] == "pass"
    assert report["selected_cases"] == 1
    assert report["attempts"] == 3
    assert len(report["dataset_sha256"]) == 64
    assert len(report["ai_config_sha256"]) == 64
    assert "not model quality" in (tmp_path / "report.md").read_text()


def test_threshold_failure_writes_report_and_exits_nonzero(tmp_path):
    argv = args(tmp_path)
    config = json.loads((ROOT / "ai-evals/smoke.thresholds.json").read_text())
    config["rules"]["gist"]["level_agreement"] = {"min": 1.1}
    path = tmp_path / "thresholds.json"
    path.write_text(json.dumps(config))
    argv[argv.index("--thresholds") + 1] = str(path)
    assert main(argv) == 1
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["status"] == "fail"
    assert report["thresholds"]["level_agreement"]["pass"] is False


def test_smoke_forbids_networked_ai_configuration(tmp_path):
    argv = args(tmp_path)
    path = tmp_path / "ai.yaml"
    path.write_text("version: 1\nroles:\n  text_ai:\n    - provider: groq\n      model: m\n")
    argv[argv.index("--ai-config") + 1] = str(path)
    assert main(argv) == 2
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["reason"] == "invalid_configuration"
    assert report["model_quality_evidence"] is False


def test_configuration_errors_do_not_echo_private_content(tmp_path, capsys):
    argv = args(tmp_path)
    private = tmp_path / "private.json"
    private.write_text('{"private-secret": "learner words"}')
    argv[argv.index("--dataset") + 1] = str(private)
    assert main(argv) == 2
    assert "learner words" not in (tmp_path / "report.json").read_text()
    assert "private-secret" not in capsys.readouterr().err


def test_unexpected_execution_failure_still_writes_safe_report(tmp_path, monkeypatch):
    async def broken(_):
        raise RuntimeError("private database URL or learner input")

    monkeypatch.setattr("listenup.ai.evals.cli.execute", broken)
    assert main(args(tmp_path)) == 2
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["reason"] == "execution_failed"
    assert "private database" not in (tmp_path / "report.json").read_text()


def test_fake_provider_never_establishes_teacher_quality(tmp_path):
    argv = args(tmp_path)
    dataset = json.loads((ROOT / "ai-evals/fixtures/gist.json").read_text())
    dataset["kind"] = "teacher"
    path = tmp_path / "teacher.json"
    path.write_text(json.dumps(dataset))
    config = json.loads((ROOT / "ai-evals/smoke.thresholds.json").read_text())
    config["scope"] = "teacher"
    config_path = tmp_path / "thresholds.json"
    config_path.write_text(json.dumps(config))
    argv[argv.index("--dataset") + 1] = str(path)
    argv[argv.index("--thresholds") + 1] = str(config_path)
    argv.remove("--offline")
    argv.remove("--smoke")
    assert main(argv) == 0
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["model_quality_evidence"] is False
    assert report["provider_acceptance"] is False


def test_report_hashes_the_dataset_bytes_used_for_evaluation(tmp_path, monkeypatch):
    import hashlib

    from listenup.ai.evals import cli

    argv = args(tmp_path)
    original = (ROOT / "ai-evals/fixtures/gist.json").read_bytes()
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_bytes(original)
    argv[argv.index("--dataset") + 1] = str(dataset_path)
    real_run = cli.run

    async def replace_after_evaluation(*args, **kwargs):
        result = await real_run(*args, **kwargs)
        dataset_path.write_text("changed after evaluation")
        return result

    monkeypatch.setattr(cli, "run", replace_after_evaluation)
    assert main(argv) == 0
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["dataset_sha256"] == hashlib.sha256(original).hexdigest()


def test_module_entrypoint_runs_cli(tmp_path, monkeypatch):
    import runpy
    import sys

    monkeypatch.setattr(sys, "argv", ["ai-evals", *args(tmp_path, "shadow")])
    with pytest.raises(SystemExit) as result:
        runpy.run_module("listenup.ai.evals", run_name="__main__")
    assert result.value.code == 0
    assert json.loads((tmp_path / "report.json").read_text())["status"] == "pass"


def test_cli_rejects_report_suffix_before_inference(tmp_path):
    argv = args(tmp_path)
    argv[argv.index("--report") + 1] = str(tmp_path / "report.txt")
    with pytest.raises(SystemExit) as result:
        main(argv)
    assert result.value.code == 2
    assert not (tmp_path / "report.txt").exists()
