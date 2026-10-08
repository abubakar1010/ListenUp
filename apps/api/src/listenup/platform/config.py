"""Application settings, read from environment variables prefixed with LISTENUP_."""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


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

    # Where the web app is served; links in emails point here.
    web_base_url: str = "http://localhost:5173"

    # Sign-in (Architecture 9.1, D17). Cookies are Secure everywhere except local runs
    # over plain http; set LISTENUP_COOKIE_SECURE to override.
    cookie_secure: bool | None = None
    session_days: int = 30
    login_lock_threshold: int = 5  # failed attempts on one account ...
    login_lock_minutes: int = 15  # ... within this many minutes lock it for as long
    login_ip_limit: int = 20  # sign-in attempts per IP ...
    login_ip_window_minutes: int = 15  # ... per window
    register_ip_limit: int = 10  # new accounts per IP per hour
    # Password reset (FR-ACC-3).
    password_reset_minutes: int = 60  # how long an emailed reset link works
    password_reset_ip_limit: int = 10  # reset requests (and, separately, resets) per IP per hour
    password_reset_email_limit: int = 3  # reset emails per address per hour

    # File uploads (FR-CI-1, FR-CI-3, D5). Sizes are binary: 500 MB is 500 MiB, as
    # operating systems show file sizes.
    upload_max_bytes: int = 500 * 1024 * 1024  # per file
    upload_quota_bytes: int = 2 * 1024 * 1024 * 1024  # stored uploads per account
    upload_confirm_hours: int = 24  # an unconfirmed upload can be confirmed this long
    upload_rate_limit: int = 30  # upload requests per learner per hour
    upload_ip_limit: int = 120  # upload requests per IP per hour (several learners may share one)

    # Intake admission per learner (System Design 4.2, D16, ADR 0027). New audio counts
    # per UTC day, each clip with at most 15 minutes (the longest passage).
    intake_daily_minutes: int = 120
    # Intakes of one learner on the shared intake lane at once, waiting or running; the
    # rest wait in the learner's own queue.
    intake_running_limit: int = 2

    # Data exports (#92, NFR-SEC-5, ADR 0030): requests per learner per UTC day (one is
    # built at a time), days a finished archive is kept, and seconds the signed link
    # behind the download endpoint works.
    export_daily_limit: int = 3
    export_keep_days: int = 7
    export_link_seconds: int = 120

    # Where media workers write source and converted files while a job runs; the
    # system's temporary directory when unset. Each job removes its own files.
    media_scratch_dir: str | None = None

    # AI providers per role (ADR 0028): a path to an ai.yaml; the packaged
    # listenup/ai/ai.yaml when unset. listenup/ai/ai.fake.yaml needs no models.
    ai_config: str | None = None

    # First retry waits about this long; later ones four times longer each time.
    job_retry_base_seconds: float = 10.0

    log_level: str = "INFO"
    # JSON logs everywhere except an interactive terminal, where plain text reads better.
    log_json: bool = True

    # YouTube intake stays off until the legal review (OQ-6) clears it.
    youtube_intake_enabled: bool = False

    # Administrators (#100, ADR 0034): accounts with one of these emails and a verified
    # address. A comma-separated list in LISTENUP_ADMIN_EMAILS; empty means no admins.
    admin_emails: Annotated[tuple[str, ...], NoDecode] = ()

    @field_validator("admin_emails", mode="before")
    @classmethod
    def _split_emails(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(email.strip() for email in value.split(",") if email.strip())
        return value

    @property
    def cookies_secure(self) -> bool:
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.environment not in ("local", "test")


@lru_cache
def get_settings() -> Settings:
    return Settings()
