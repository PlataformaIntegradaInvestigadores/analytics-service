"""Development-only document preparation and topic-output contracts."""

from typing import Any, Literal

from pydantic import Field, model_validator

from app.schemas.analytics import Contract


class Preparation(Contract):
    missing_abstract: Literal["exclude", "title_only"] = "exclude"
    duplicates: Literal["keep", "exclude_later"] = "exclude_later"
    min_tokens: int = Field(default=5, ge=1, le=10000, strict=True)
    start_year: int = Field(default=2020, ge=1, le=9999, strict=True)
    end_year: int = Field(default=2025, ge=1, le=9999, strict=True)

    @model_validator(mode="after")
    def ordered(self):
        if self.start_year > self.end_year:
            raise ValueError("Start year must not exceed end year")
        return self


class Article(Contract):
    article_id: str
    title: str
    publication_date: str
    has_abstract: bool
    author_count: int
    descriptor_count: int


class ArticlePage(Contract):
    status: Literal["ok", "empty"]
    total: int
    offset: int
    limit: int
    items: list[Article]


class Detail(Contract):
    article_id: str
    document: dict[str, Any]
    authors: list[str]
    descriptors: list[str]


class DescriptorPage(Contract):
    status: Literal["ok", "empty"]
    total: int
    offset: int
    limit: int
    items: list[dict[str, Any]]


class TopicOutputs(Contract):
    model_version: str = Field(min_length=1, max_length=256)
    fit_document_ids: list[str] = Field(min_length=1, max_length=100000)
    assignments: dict[str, str] = Field(max_length=100000)
    terms: dict[str, list[str]] = Field(min_length=1, max_length=100)


class Candidate(Contract):
    name: str = Field(min_length=1, max_length=100)
    configuration: dict[str, Any] = Field(default_factory=dict)
