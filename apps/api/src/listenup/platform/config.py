"""Application settings, read from environment variables prefixed with LISTENUP_."""

from functools import lru_cache
from typing import Literal

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

    # Outgoing email (Architecture 4.1, notifications). Locally Mailpit takes
    # everything on port 1025 without auth; production sets a provider's host, port,
    # login and "starttls" or "ssl".
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_security: Literal["none", "starttls", "ssl"] = "none"
    smtp_timeout_seconds: float = 10.0
    smtp_sender: str = "ListenUp <no-reply@listenup.local>"

    # Sign-in (Architecture 9.1, D17). Cookies are Secure everywhere except local runs
    # over plain http; set LISTENUP_COOKIE_SECURE to override.
    cookie_secure: bool | None = None
    session_days: int = 30
    login_lock_threshold: int = 5  # failed attempts on one account ...
    login_lock_minutes: int = 15  # ... within this many minutes lock it for as long
    login_ip_limit: int = 20  # sign-in attempts per IP ...
    login_ip_window_minutes: int = 15  # ... per window
    register_ip_limit: int = 10  # new accounts per IP per hour

    # First retry waits about this long; later ones four times longer each time.
    job_retry_base_seconds: float = 10.0

    log_level: str = "INFO"
    # JSON logs everywhere except an interactive terminal, where plain text reads better.
    log_json: bool = True

    # YouTube intake stays off until the legal review (OQ-6) clears it.
    youtube_intake_enabled: bool = False

    @property
    def cookies_secure(self) -> bool:
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.environment not in ("local", "test")


@lru_cache
def get_settings() -> Settings:
    return Settings()
