"""Alembic environment (Database Design 12.2).

Every migration runs with `lock_timeout = '5s'`, so a migration that would wait behind
live traffic fails fast instead of stalling the app. The URL is taken from
`sqlalchemy.url` when a caller sets it (the tests do), otherwise from
LISTENUP_DATABASE_URL.
"""

from typing import Any

from alembic import context
from sqlalchemy import create_engine, text

from listenup.modules.analytics import models as _analytics_models  # noqa: F401
from listenup.modules.blind import models as _blind_models  # noqa: F401
from listenup.modules.content import models as _content_models  # noqa: F401
from listenup.modules.dictation import models as _dictation_models  # noqa: F401
from listenup.modules.export import models as _export_models  # noqa: F401
from listenup.modules.identity import models as _identity_models  # noqa: F401
from listenup.modules.practice import models as _practice_models  # noqa: F401
from listenup.platform import models as _platform_models  # noqa: F401
from listenup.platform.config import get_settings
from listenup.platform.db import APP_SCHEMAS, Base, to_sqlalchemy_url

config = context.config
target_metadata = Base.metadata


def database_url() -> str:
    return config.get_main_option("sqlalchemy.url") or to_sqlalchemy_url(
        get_settings().database_url
    )


def include_name(name: str | None, type_: str, parent_names: dict[str, Any]) -> bool:
    # Compare only the application schemas; `public` holds alembic_version and the
    # job queue, which Procrastinate manages.
    if type_ == "schema":
        return name in APP_SCHEMAS
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        include_schemas=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.execute("SET lock_timeout = '5s'")
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(database_url())
    with engine.connect() as connection:
        connection.execute(text("SET lock_timeout = '5s'"))
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_name=include_name,
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
