from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    fulfillos_env: str = "development"
    database_url: str = "sqlite:///./fulfillos.db"
    fulfillos_jwt_secret: str = "development-only-secret"
    fulfillos_access_token_minutes: int = 30
    fulfillos_refresh_token_days: int = 14
    cors_origins: str = "http://localhost:3000"
    redis_url: str | None = None
    nats_url: str | None = None
    mongodb_uri: str | None = None
    mongodb_database: str = "fulfillos_telemetry"

    @property
    def cors_origin_list(self) -> list[str]:
        return [value.strip() for value in self.cors_origins.split(",") if value.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
