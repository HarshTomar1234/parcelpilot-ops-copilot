"""Environment configuration. See .env.example for the documented surface.

Nothing here has a business meaning of its own - the business calendar
fields are configuration for a future phase (ADR-007), not logic executed
by anything in Phase 1.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    parcelpilot_source_dir: Path | None = None
    parcelpilot_db_path: Path = Path("build/parcelpilot.db")

    business_timezone: str = "Asia/Kolkata"
    business_days: str = "Mon,Tue,Wed,Thu,Fri"
    business_hours_start: str = "09:00"
    business_hours_end: str = "18:00"


def get_settings() -> Settings:
    return Settings()
