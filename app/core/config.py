from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ANALYTICS_", env_file=".env", extra="ignore"
    )

    environment: Literal["local", "staging", "production"] = "local"
    public_base_path: str = "/api/v1"
    port: int = Field(default=8006, ge=1024, le=65535)
    artifact_database: Path | None = None
    corpus_database: Path | None = None
    workset_database: Path | None = None
    workset_directory: Path | None = None
    max_request_bytes: int = Field(
        default=8 * 1024 * 1024, ge=1024, le=64 * 1024 * 1024
    )

    @field_validator("public_base_path")
    @classmethod
    def validate_public_base_path(cls, value: str) -> str:
        if (
            not value.startswith("/")
            or any(character in value for character in ("?", "#", "\\", "{", "}"))
            or "//" in value
            or any(character.isspace() for character in value)
        ):
            raise ValueError("Use an absolute URL path without query or fragment")
        return value.rstrip("/") or "/"
