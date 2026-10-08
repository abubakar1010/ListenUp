"""Report the five PRD 2 success metrics for a date range (#101, ADR 0033).

Run from apps/api. Dates are UTC days and both ends are included:

    uv run python scripts/analytics_report.py --from 2026-10-01 --to 2026-10-31 [--json]

Connect as a login granted `listenup_readonly` (--database-url or
LISTENUP_DATABASE_URL): that role reads every learner's analytics events but no
account data, so the report only ever sees pseudonymous learner ids. Connected as the
database owner locally, add `--role listenup_readonly` for the same view. The report
runs in a read-only transaction. Follow-up events (completions, listens, returns) are
counted up to --as-of, by default now.
"""

import argparse
import asyncio
import dataclasses
import json
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import text

from listenup.modules.analytics import service as analytics
from listenup.platform.config import get_settings
from listenup.platform.database import Database

READONLY_ROLE = "listenup_readonly"
# SET LOCAL ROLE does not pick up the role's own statement_timeout (ALTER ROLE ... SET
# applies at login only), so the report sets one itself.
STATEMENT_TIMEOUT = "30s"


def _day(value: str) -> datetime:
    return datetime.combine(date.fromisoformat(value), time(), tzinfo=UTC)


def _moment(value: str) -> datetime:
    moment = datetime.fromisoformat(value)
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


async def build(
    database_url: str, start: datetime, end: datetime, as_of: datetime, role: str | None
) -> analytics.Report:
    database = Database(database_url, pool_size=1)
    try:
        async with database.transaction() as db:
            await db.execute(text("SET TRANSACTION READ ONLY"))
            await db.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
            if role == READONLY_ROLE:
                await db.execute(text(f"SET LOCAL ROLE {READONLY_ROLE}"))
            return await analytics.build_report(db, start, end, as_of)
    finally:
        await database.dispose()


def _percent(rate: float | None) -> str:
    return "n/a" if rate is None else f"{rate:.0%}"


def _seconds(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0f} s"


def as_text(report: analytics.Report) -> str:
    last_day = (report.end - timedelta(days=1)).date()
    plans, listen, back = report.plan_completion, report.first_listen, report.return_rate
    lines = [
        f"ListenUp success metrics, {report.start.date()} to {last_day} "
        f"(followed to {report.as_of:%Y-%m-%d %H:%M} UTC)",
        "",
        f"Plan completion rate   {_percent(plans.reach_rate)} reached the final step, "
        f"{_percent(plans.completion_rate)} completed "
        f"({plans.reached_final_step} and {plans.completed} of {plans.started} plans)",
        f"Time to first listen   median {_seconds(listen.median_seconds)}, "
        f"90th percentile {_seconds(listen.p90_seconds)}, "
        f"{_percent(listen.under_target_rate)} under 60 s "
        f"({listen.listened} of {listen.clips_added} clips listened to)",
        f"Return rate            {_percent(back.rate)} started 3+ plans in 14 days "
        f"({back.returned} of {back.new_learners} new learners; "
        f"{back.window_open} still inside their 14 days)",
    ]
    reuse = report.mark_reuse
    if reuse is None:
        lines.append("Mark reuse             no data (cards and Shadow are not recorded yet)")
    else:
        lines.append(
            f"Mark reuse             {_percent(reuse.rate)} "
            f"({reuse.cards} cards and {reuse.shadow_segments} Shadow segments over "
            f"{reuse.sessions_reached_transcript} sessions that reached Transcript)"
        )
    trend = report.repeat_failures
    if trend is None:
        lines.append("Repeat-failure trend   no data (no marks in this range)")
    else:
        lines.append(
            f"Repeat-failure trend   {_percent(trend.share)} of {trend.marks} marks repeat "
            "an earlier session's"
            + (
                f" ({trend.unnumbered} from sessions without a start event)"
                if trend.unnumbered
                else ""
            )
        )
        lines.extend(
            f"  session {s.session_number}: {_percent(s.share)} of {s.marks} marks"
            for s in trend.by_session
        )
    return "\n".join(lines)


def _plain(value: Any) -> Any:
    """JSON-ready form of a report: dataclass fields plus their computed properties.

    The rates are properties, which `dataclasses.asdict` leaves out; reading them from
    the class keeps a rate added later in the JSON without touching this script.
    """
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        body = {f.name: _plain(getattr(value, f.name)) for f in dataclasses.fields(value)}
        for name, attr in vars(type(value)).items():
            if isinstance(attr, property):
                body[name] = _plain(getattr(value, name))
        return body
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    return value


def as_json(report: analytics.Report) -> str:
    return json.dumps(_plain(report), indent=2)


def main(argv: list[str] | None = None) -> str:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from", dest="start", required=True, help="first day, YYYY-MM-DD")
    parser.add_argument("--to", dest="last", required=True, help="last day, YYYY-MM-DD")
    parser.add_argument("--as-of", help="follow events up to this ISO time (default: now)")
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    parser.add_argument("--role", choices=[READONLY_ROLE], help="switch to this role first")
    parser.add_argument("--database-url", default=get_settings().database_url)
    args = parser.parse_args(argv)

    start, end = _day(args.start), _day(args.last) + timedelta(days=1)
    if end <= start:
        parser.error("--to must be on or after --from")
    as_of = _moment(args.as_of) if args.as_of else datetime.now(UTC)
    report = asyncio.run(build(args.database_url, start, end, as_of, args.role))
    return as_json(report) if args.json else as_text(report)


if __name__ == "__main__":
    print(main())
