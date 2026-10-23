"""ai-evals command. Offline means fake AI; durable gateway accounting still applies."""

import argparse
import asyncio
import hashlib
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from listenup.ai.accounting import PostgresAccounting
from listenup.ai.config import load_config
from listenup.ai.errors import AIConfigError
from listenup.ai.evals.models import Dataset, Thresholds
from listenup.ai.evals.runner import run
from listenup.ai.gateway import AIGateway
from listenup.platform.config import get_settings
from listenup.platform.database import Database


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    lines = [
        "# AI evaluation report",
        "",
        str(report.get("notice", "Evaluation did not complete.")),
        "",
        f"Status: **{report['status']}**",
        "",
        f"Reason: {report.get('reason') or 'completed'}",
        "",
        f"Execution: {report.get('execution', 'none')}",
        "",
        "| Metric | Actual | Required | Pass |",
        "| --- | ---: | --- | --- |",
    ]
    for name, decision in report.get("thresholds", {}).items():
        limit = f">= {decision['min']}" if "min" in decision else f"<= {decision['max']}"
        lines.append(f"| {name} | {decision['actual']:.6g} | {limit} | {decision['pass']} |")
    lines.extend(["", "The JSON report contains case/run results, provenance and fingerprints."])
    path.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")


async def execute(args: argparse.Namespace) -> dict[str, Any]:
    dataset_bytes = args.dataset.read_bytes()
    threshold_bytes = args.thresholds.read_bytes()
    dataset = Dataset.model_validate_json(dataset_bytes)
    thresholds = Thresholds.model_validate_json(threshold_bytes)
    settings = get_settings()
    config_path = args.ai_config or (Path(settings.ai_config) if settings.ai_config else None)
    config = load_config(config_path)
    # Restrict the entire registry selection, including fallback roles, before any call.
    if args.offline and any(
        e.provider != "fake" for entries in config.roles.values() for e in entries
    ):
        raise ValueError("offline requires exclusively fake provider entries")
    database = Database(settings.database_url)
    try:
        gateway = AIGateway(
            config, environment=settings.environment, accounting=PostgresAccounting(database)
        )
        order = config.tasks.get("grade_gist", ()) if dataset.suite == "gist" else ()
        report = await run(
            dataset,
            thresholds,
            gateway,
            smoke=args.smoke,
            offline=args.offline,
            task_provider=order[0] if order else None,
        )
    finally:
        await database.dispose()
    report.update(
        dataset_sha256=hashlib.sha256(dataset_bytes).hexdigest(),
        thresholds_sha256=hashlib.sha256(threshold_bytes).hexdigest(),
        ai_config_sha256=hashlib.sha256(config.model_dump_json().encode()).hexdigest(),
        revision=args.revision,
    )
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--thresholds", type=Path, required=True)
    parser.add_argument("--ai-config", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--revision", default="unknown")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args(argv)
    if args.report.suffix != ".json":
        parser.error("--report must have a .json suffix")
    try:
        report = asyncio.run(execute(args))
        exit_code = 0 if report["status"] == "pass" else 1
    except (ValueError, ValidationError, AIConfigError, OSError):
        # Errors from parsers can quote private dataset fields or connection strings.
        report = {
            "version": 1,
            "status": "error",
            "reason": "invalid_configuration",
            "model_quality_evidence": False,
            "provider_acceptance": False,
        }
        exit_code = 2
        print("ai-evals: invalid dataset, thresholds or AI configuration", file=sys.stderr)
    except Exception:
        report = {
            "version": 1,
            "status": "error",
            "reason": "execution_failed",
            "model_quality_evidence": False,
            "provider_acceptance": False,
        }
        exit_code = 2
        print("ai-evals: execution failed; inspect service health", file=sys.stderr)
    write_report(args.report, report)
    return exit_code
