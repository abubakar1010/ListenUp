"""Application settings, read from environment variables prefixed with LISTENUP_."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LISTENUP_", env_file=".env", extra="ignore")

    environment: str = "local"
    database_url: str = "postgresql://listenup:listenup@localhost:5432/listenup"
    database_pool_size: int = 5

    s3_endpoint_url: str = "http://localhost:9000"
    # Endpoint used in signed URLs handed to the browser. Inside Docker Compose the
    # API reaches storage at http://storage:9000, which the browser cannot resolve.
    s3_public_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_access_key: str = "listenup"
    s3_secret_key: SecretStr = SecretStr("listenup-local-only")
    s3_bucket: str = "listenup"
    # Signed URLs live for minutes and are reused until 80% of their lifetime.
    signed_url_ttl_seconds: int = 300

    smtp_host: str = "localhost"
    smtp_port: int = 1025

    log_level: str = "INFO"
    # JSON logs everywhere except an interactive terminal, where plain text reads better.
    log_json: bool = True

    # YouTube intake stays off until the legal review (OQ-6) clears it.
    youtube_intake_enabled: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
