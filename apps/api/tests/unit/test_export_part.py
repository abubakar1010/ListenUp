"""Module contributions to a data export name tables from code only (#92)."""

import uuid

import pytest

from listenup.platform.export import learner_rows


@pytest.mark.parametrize(
    ("table", "column"),
    [("content.contents; DROP TABLE x", "user_id"), ("content.contents", "user_id OR 1=1")],
)
@pytest.mark.anyio
async def test_learner_rows_refuses_anything_but_plain_names(table: str, column: str) -> None:
    with pytest.raises(ValueError, match="plain SQL name"):
        await learner_rows(None, table, uuid.uuid4(), column=column)  # type: ignore[arg-type]
