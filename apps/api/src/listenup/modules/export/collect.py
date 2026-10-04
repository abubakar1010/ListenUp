"""Which modules contribute to a data export (#92, ADR 0030).

Each entry is a module's `export_data` from its service.py (see
`listenup.platform.export`). A module that gets its first learner table adds its
function here; `tests/integration/test_export.py` fails while any table with a
`user_id` column is missing from the export.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.blind import service as blind
from listenup.modules.content import service as content
from listenup.modules.dictation import service as dictation
from listenup.modules.identity import service as identity
from listenup.modules.practice import service as practice
from listenup.platform.export import Contributor, ExportPart, learner_rows


async def _own_data(session: AsyncSession, learner: uuid.UUID) -> ExportPart:
    """The platform's request records and the learner's earlier export requests.

    The request hash of an idempotency key only detects a reused key; it is left out.
    """
    return ExportPart(
        tables=(
            await learner_rows(
                session,
                "ops.idempotency_keys",
                learner,
                omit=("request_hash",),
                order_by="created_at",
            ),
            await learner_rows(
                session, "ops.data_exports", learner, omit=("archive_key",), order_by="requested_at"
            ),
        )
    )


CONTRIBUTORS: tuple[Contributor, ...] = (
    identity.export_data,
    content.export_data,
    practice.export_data,
    blind.export_data,
    dictation.export_data,
    _own_data,
)


async def collect(session: AsyncSession, learner: uuid.UUID) -> list[ExportPart]:
    return [await contribute(session, learner) for contribute in CONTRIBUTORS]
