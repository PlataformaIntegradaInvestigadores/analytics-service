"""Prespecified publication-year reconstruction protocol."""

from pydantic import Field, model_validator

from app.schemas.analytics import Contract


class StudyProtocol(Contract):
    start_year: int = Field(default=2000, ge=1900, le=2100, strict=True)
    topic_fit_end: int = Field(default=2015, ge=1900, le=2100, strict=True)
    validation_end: int = Field(default=2018, ge=1900, le=2100, strict=True)
    test_end: int = Field(default=2021, ge=1900, le=2100, strict=True)
    topic_candidates: list[int] = Field(
        default_factory=lambda: [6, 8, 10], min_length=1, max_length=5
    )
    ridge_alphas: list[float] = Field(
        default_factory=lambda: [0.1, 1.0, 10.0, 100.0], min_length=1, max_length=8
    )
    max_features: int = Field(default=5000, ge=100, le=10000, strict=True)
    min_df: int = Field(default=3, ge=1, le=100, strict=True)
    seed: int = Field(default=42, ge=0, le=2**32 - 1, strict=True)
    approval_reference: str = Field(min_length=5, max_length=2000)
    rationale: str = Field(min_length=20, max_length=4000)

    @model_validator(mode="after")
    def chronological(self):
        if not (
            self.start_year + 8
            <= self.topic_fit_end
            < self.validation_end
            < self.test_end
            and self.test_end - self.start_year <= 100
        ):
            raise ValueError("Ordered, bounded train/validation/test years required")
        if (
            len(set(self.topic_candidates)) != len(self.topic_candidates)
            or any(
                type(k) is not int or not 2 <= k <= 30 for k in self.topic_candidates
            )
            or any(not 0 < a <= 100000 for a in self.ridge_alphas)
            or len(set(self.ridge_alphas)) != len(self.ridge_alphas)
        ):
            raise ValueError("Unique bounded candidate parameters required")
        return self
