"""
Shared configuration using Pydantic BaseSettings.
Reads from environment variables and .env file.
"""
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "/opt/media-platform/.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # General
    env: str = "production"
    log_level: str = "INFO"
    platform_name: str = "media-platform"
    platform_version: str = "0.1.0"

    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "media_platform"
    postgres_user: str = "media"
    postgres_password: str = "Mp@Secure2024"
    postgres_pool_size: int = 10
    postgres_max_overflow: int = 20
    postgres_pool_timeout: int = 30

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def sync_database_url(self) -> str:
        """For Alembic migrations (synchronous)."""
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = "Redis@Secure2024"
    redis_consumer_group: str = "media-platform"

    @property
    def redis_url(self) -> str:
        return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/0"

    # Storage paths
    media_root: Path = Path("/opt/media-platform/data")
    library_root: Path = Path("/opt/media-platform/data/library")
    download_root: Path = Path("/opt/media-platform/data/downloads")
    subtitle_root: Path = Path("/opt/media-platform/data/subtitles")
    metadata_root: Path = Path("/opt/media-platform/data/metadata")
    cache_root: Path = Path("/opt/media-platform/data/cache")
    temp_root: Path = Path("/opt/media-platform/data/temp")
    log_root: Path = Path("/opt/media-platform/logs")

    # Jellyfin
    jellyfin_url: str = "http://jellyfin:8096"
    jellyfin_api_key: str = ""
    jellyfin_user_id: str = ""

    # Media API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_secret_key: str = "7f3d8a2c1e9b4f6d0a5c8e3b7f2d9a4c6e1b8f5d0a3c7e2b9f4d1a6c3e8b5f2"
    api_access_token_expire_minutes: int = 10080
    api_cors_origins: str = "http://localhost:3000,http://localhost:8080"

    # Telegram
    telegram_bot_token: str = ""
    telegram_allowed_chat_ids: str = ""
    telegram_admin_ids: str = ""

    @property
    def telegram_allowed_chat_id_list(self) -> List[int]:
        if not self.telegram_allowed_chat_ids:
            return []
        return [int(i.strip()) for i in self.telegram_allowed_chat_ids.split(",") if i.strip()]

    # TMDb
    tmdb_api_key: str = ""
    tmdb_base_url: str = "https://api.themoviedb.org/3"

    # Subtitles
    opensubtitles_api_key: str = ""
    subdl_api_key: str = ""
    subtitle_languages: str = "en,ml"

    @property
    def subtitle_language_list(self) -> List[str]:
        return [lang.strip() for lang in self.subtitle_languages.split(",") if lang.strip()]

    # Quality
    quality_preference: str = "2160p,1080p,720p,480p"
    quality_prefer_hdr: bool = True
    quality_prefer_hevc: bool = True

    # Storage thresholds (GB)
    storage_warning_threshold_gb: int = 100
    storage_critical_threshold_gb: int = 50

    # Health check schedule
    health_check_schedule: str = "0 2 * * *"

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"log_level must be one of {allowed}")
        return upper


@lru_cache
def get_settings() -> Settings:
    """
    Cached settings instance.
    Use this everywhere to avoid re-reading .env on every call.

    Usage:
        from shared.config.settings import get_settings
        settings = get_settings()
    """
    return Settings()


# Convenience singleton
settings = get_settings()
