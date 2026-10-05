"""What each module contributes to a learner's data export (#92, NFR-SEC-5, ADR 0030).

The export module builds the archive, but it never reads another module's tables
itself: each module that owns learner data offers

    async def export_data(session: AsyncSession, learner: uuid.UUID) -> ExportPart

in its `service.py`, returning its tables' rows for that learner and the stored files
that belong in the archive. A module that adds a learner table (marks, cards,
recordings ...) adds the table to its `export_data`, and its module's function to
`export/collect.py` if it is new; an integration test fails while any table with a
`user_id` column is missing from the export.

These types live in the platform package so that every module can return them
without importing the export module, which imports them all.
"""

import re
import uuid
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

Row = dict[str, Any]


@dataclass(frozen=True)
class ExportTable:
    """One table's rows for the learner, with the columns that were left out.

    Rows hold database values as they come (UUIDs, datetimes, ranges ...); the export
    module turns them into JSON.
    """

    name: str  # schema-qualified, for example "content.contents"
    rows: list[Row]
    omitted: tuple[str, ...] = ()  # secrets and internal storage details, never exported


@dataclass(frozen=True)
class ExportFile:
    """A stored object to copy into the archive.

    `key` must lie under the learner's own prefix `users/<learner>/`; the export job
    skips anything else, so a mistake can never copy another learner's file.
    """

    key: str
    path: str  # where it goes in the archive, for example "media/<id>/playback.mp4"


@dataclass(frozen=True)
class ExportPart:
    tables: tuple[ExportTable, ...] = ()
    files: tuple[ExportFile, ...] = field(default_factory=tuple)


Contributor = Callable[[AsyncSession, uuid.UUID], Awaitable[ExportPart]]

_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")


def _identifier(name: str) -> str:
    """A table or column name from our own code; anything else is refused."""
    parts = name.split(".")
    if not 1 <= len(parts) <= 2 or not all(_NAME.match(part) for part in parts):
        raise ValueError(f"not a plain SQL name: {name!r}")
    return name


async def select_rows(
    session: AsyncSession, sql: str, params: dict[str, Any], omit: Iterable[str] = ()
) -> list[Row]:
    """Run `sql` and return its rows as dicts without the `omit` columns."""
    left_out = set(omit)
    result = await session.execute(text(sql), params)
    return [
        {name: value for name, value in row.items() if name not in left_out}
        for row in result.mappings()
    ]


async def learner_rows(
    session: AsyncSession,
    table: str,
    learner: uuid.UUID,
    *,
    column: str = "user_id",
    omit: tuple[str, ...] = (),
    order_by: str | None = None,
) -> ExportTable:
    """Every row of `table` whose `column` is the learner, every column but `omit`.

    The filter is explicit: the export job runs as the workers' role, which bypasses
    row-level security. `SELECT *` means a column added later is exported without
    changing this code; a secret column must be named in `omit`.
    """
    order = f" ORDER BY {_identifier(order_by)}" if order_by else ""
    sql = f"SELECT * FROM {_identifier(table)} WHERE {_identifier(column)} = :learner{order}"
    rows = await select_rows(session, sql, {"learner": learner}, omit)
    return ExportTable(table, rows, omit)
