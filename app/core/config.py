from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = "development"

    database_url: str
    db_pool_size: int = 5
    db_max_overflow: int = 10

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14
    invite_expire_days: int = 7

    task_list_default_limit: int = 50
    task_list_max_limit: int = 100

    list_default_limit: int = 50
    list_max_limit: int = 100

    attachment_storage_dir: str = "var/attachments"
    attachment_max_bytes: int = 10 * 1024 * 1024
    attachment_max_per_task: int = 20

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
