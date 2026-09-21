"""任务请求与人工编辑输入的边界校验。"""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.api.serializers import arxiv_url, doi_url

Year = Annotated[int, Field(ge=2023, le=2100, strict=True)]


class CrawlTriggerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["weekly", "backfill", "pdf"]
    years: list[Year] | None = Field(default=None, min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_years(self):
        if self.years is not None:
            if self.scope != "backfill" or len(set(self.years)) != len(self.years):
                raise ValueError("years 仅用于 backfill，且不得重复")
            self.years = sorted(self.years)
        return self


class PaperCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=1000)
    venue_abbr: str = Field(min_length=1, max_length=64)
    year: int = Field(ge=2000, le=2100)
    doi: str | None = Field(default=None, max_length=512)
    dblp_key: str | None = Field(default=None, max_length=256, pattern=r"^(?:conf|journals)/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
    arxiv_id: str | None = Field(default=None, max_length=256)

    @field_validator("doi")
    @classmethod
    def valid_doi(cls, value):
        if value is not None and doi_url(value) is None:
            raise ValueError("doi 格式无效")
        return value

    @field_validator("arxiv_id")
    @classmethod
    def valid_arxiv(cls, value):
        if value is not None and arxiv_url(value) is None:
            raise ValueError("arxiv_id 格式无效")
        return value

    @model_validator(mode="after")
    def needs_identity(self):
        if not (self.dblp_key or self.doi or self.arxiv_id):
            raise ValueError("dblp_key、doi、arxiv_id 至少提供一个")
        return self


class PaperPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    directions: list[str] | None = Field(default=None, max_length=50)
    note: str | None = Field(default=None, max_length=2000)


class RuleCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    direction_code: str = Field(min_length=1, max_length=64)
    keyword: str = Field(min_length=1, max_length=500)
    field: Literal["title", "abstract", "both"] = "both"
    weight: float = Field(default=1.0, gt=0, le=10, allow_inf_nan=False)
    enabled: int = Field(default=1, ge=0, le=1)


class VenueUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    abbr: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9 ._-]*$")
    name: str = Field(min_length=1, max_length=300)
    dblp_stream: str = Field(pattern=r"^(conf|journals)/[A-Za-z0-9._-]+$")
    dblp_toc_pattern: str | None = Field(default=None, max_length=128, pattern=r"^[A-Za-z0-9._{}-]+$")
    issn: str | None = Field(default=None, pattern=r"^\d{4}-\d{3}[0-9Xx]$")
    openalex_source_id: str | None = Field(default=None, pattern=r"^S\d+$")
    s2_venue: str | None = Field(default=None, max_length=200)
    type: Literal["conf", "journal"]
    ccf_level: Literal["A", "B"]
    ccf_area: str = Field(default="人工智能", min_length=1, max_length=128)
    active: int = Field(default=1, ge=0, le=1)
