"""Database metadata shared by every module's models.

The schema itself is created by the Alembic migrations in apps/api/migrations; the
models mirror it so that `alembic check` can report drift (Database Design 12.2).
"""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Schemas owned by the application (Database Design 1.1). The job queue tables in
# `public` are managed by Procrastinate and are not modelled.
APP_SCHEMAS = ("identity", "content", "practice", "grading", "ai", "ops")


def to_sqlalchemy_url(database_url: str) -> str:
    """Point a plain postgresql:// URL at the psycopg 3 driver."""
    for prefix in ("postgresql://", "postgres://"):
        if database_url.startswith(prefix):
            return "postgresql+psycopg://" + database_url[len(prefix) :]
    return database_url


class Base(DeclarativeBase):
    metadata = MetaData()
