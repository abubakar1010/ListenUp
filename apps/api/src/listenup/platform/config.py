"""Application settings, read from environment variables prefixed with LISTENUP_."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LISTENUP_", env_file=".env", extra="ignore")

    environment: str = "local"
    database_url: str = "postgresql://listenup:listenup@localhost:5432/listenup"
    s3_endpoint_url: str = "http://localhost:9000"
    s3_bucket: str = "listenup"
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    # YouTube intake stays off until the legal review (OQ-6) clears it.
    youtube_intake_enabled: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
