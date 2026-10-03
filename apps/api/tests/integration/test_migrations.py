"""Migration checks from Database Design 12.2 and story #27."""

from collections.abc import Callable

import psycopg
from alembic import command
from alembic.script import ScriptDirectory

from tests.integration.conftest import alembic_config


def test_upgrade_downgrade_one_and_upgrade_again(make_database: Callable[[], str]) -> None:
    config = alembic_config(make_database())

    command.upgrade(config, "head")
    command.downgrade(config, "-1")
    command.upgrade(config, "head")
    # Raises if the models and the migrated schema have drifted apart.
    command.check(config)


def test_full_downgrade_leaves_an_empty_database(make_database: Callable[[], str]) -> None:
    url = make_database()
    config = alembic_config(url)
    command.upgrade(config, "head")
    command.downgrade(config, "base")

    with psycopg.connect(url) as conn:
        schemas = conn.execute(
            "SELECT nspname FROM pg_namespace WHERE nspname IN "
            "('identity', 'content', 'practice', 'grading', 'ai', 'ops')"
        ).fetchall()
    assert schemas == []


def test_history_is_linear(make_database: Callable[[], str]) -> None:
    script = ScriptDirectory.from_config(alembic_config(make_database()))
    assert len(script.get_heads()) == 1


def test_migrations_set_a_lock_timeout(make_database: Callable[[], str], capsys: object) -> None:
    command.upgrade(alembic_config(make_database()), "head", sql=True)
    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "SET lock_timeout = '5s'" in output
