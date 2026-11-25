from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

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
    model_database: Path | None = None
    study_database: Path | None = None
    review_database: Path | None = None
    lake_directory: Path | None = None
    identity_validation_url: str | None = None
    identity_allowed_users: list[str] = Field(default_factory=list)
    identity_timeout_seconds: float = Field(default=3.0, ge=0.1, le=10)
    corpus_database: Path | None = None
    workset_database: Path | None = None
    workset_directory: Path | None = None
    max_request_bytes: int = Field(
        default=8 * 1024 * 1024, ge=1024, le=64 * 1024 * 1024
    )

    @field_validator("identity_validation_url")
    @classmethod
    def validate_identity_url(cls, value):
        if value is None:
            return value
        url = urlsplit(value)
        _ = url.port
        if (
            url.scheme not in ("http", "https")
            or any(c.isspace() for c in value)
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path != "/internal/auth/validate-token/"
            or (
                url.scheme == "http"
                and url.hostname
                not in ("identity-service", "localhost", "127.0.0.1", "::1")
            )
        ):
            raise ValueError("Use the existing trusted Centinela validation endpoint")
        return value

    @field_validator("identity_allowed_users")
    @classmethod
    def validate_allowed_users(cls, value):
        if any(
            not user.isascii() or not user.isalnum() or len(user) > 128
            for user in value
        ):
            raise ValueError("Use Centinela principal identifiers")
        return sorted(set(value))

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
