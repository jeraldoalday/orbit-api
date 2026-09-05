from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = "development"

    database_url: str
    db_pool_size: int = 5
    db_max_overflow: int = 10

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    # bcrypt's cost factor. 12 is the production default; the test suite drops
    # it to the minimum, since hashing dominates the runtime of a suite that
    # registers a handful of users per test and never checks hash strength.
    # Bounded by what bcrypt itself accepts, so a typo fails at startup rather
    # than on the first login.
    bcrypt_rounds: int = Field(default=12, ge=4, le=31)
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14
    invite_expire_days: int = 7

    task_list_default_limit: int = 50
    task_list_max_limit: int = 100

    list_default_limit: int = 50
    list_max_limit: int = 100

    # A bulk edit costs one UPDATE plus its activity, notification and
    # webhook rows per task, all inside one request. The ceiling keeps a
    # single call from turning into an unbounded amount of work.
    bulk_task_max_items: int = 100

    # A checklist is meant to be read at a glance and is rewritten whole by a
    # reorder. Past this it is a task list wearing a task's clothes.
    checklist_max_items: int = 100

    # One request turning into an unbounded CSV is the same problem the task
    # list solves with pagination; an export just needs a much higher ceiling
    # to still be worth having.
    export_max_rows: int = 5000

    attachment_storage_dir: str = "var/attachments"
    attachment_max_bytes: int = 10 * 1024 * 1024
    attachment_max_per_task: int = 20
    # The count cap alone bounds a task at count x per-file size, which is an
    # order of magnitude more than anyone means to allow. This is the number
    # that actually bounds what one task can cost in storage.
    attachment_max_total_bytes_per_task: int = 50 * 1024 * 1024

    webhook_max_per_org: int = 10
    webhook_max_attempts: int = 5
    webhook_timeout_seconds: float = 10.0
    # Retries back off as base * 2 ** (attempt - 1): 60s, 2m, 4m, 8m.
    webhook_backoff_base_seconds: int = 60
    webhook_batch_size: int = 50
    # How long a worker owns a claimed batch. Must outlast one HTTP attempt,
    # or a slow endpoint lets a second worker pick the row up mid-flight.
    webhook_lease_seconds: int = 120
    # Resolving a target hostname is a best-effort SSRF filter; it is turned
    # off in tests, where no name should be looked up at all.
    webhook_validate_dns: bool = True

    rate_limit_enabled: bool = True
    rate_limit_requests: int = 300
    rate_limit_window_seconds: int = 60
    auth_rate_limit_requests: int = 10
    auth_rate_limit_window_seconds: int = 60

    cors_origins: Optional[str] = None

    log_level: str = "INFO"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def cors_origin_list(self) -> list:
        if not self.cors_origins:
            return []
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
