"""Validated application settings with stable, module-relative data paths."""
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(PROJECT_ROOT / ".env"), str(BACKEND_ROOT / ".env")),
        env_file_encoding="utf-8", extra="ignore",
    )
    database_url: str = "sqlite:///" + (BACKEND_ROOT / "data" / "papers.db").as_posix()
    papers_root: Path = BACKEND_ROOT / "papers"
    seeds_dir: Path = PROJECT_ROOT / "seeds"
    initialize_on_startup: bool = True
    scheduler_enabled: bool = True
    startup_crawl_enabled: bool = True
    startup_year_from: int = Field(default=2023, ge=2000, le=2100)
    startup_year_to: int | None = Field(default=None, ge=2000, le=2100)
    snapshot_enabled: bool = True
    snapshot_dir: Path = PROJECT_ROOT / "frontend" / "static" / "snapshot"
    pages_publish_enabled: bool = False
    pages_repository: str = ""
    pages_site_url: str = ""
    pages_token_file: Path = Path("/run/secrets/github_token")
    pages_retry_seconds: int = Field(default=300, ge=60, le=86400)
    pages_deploy_retry_seconds: int = Field(default=1800, ge=300, le=86400)
    dblp_base_url: str = "https://dblp.org"
    s2_api_key: str = Field(default="", repr=False)
    contact_email: str = ""
    dblp_rps: float = Field(default=1.0, gt=0, le=1)
    s2_rps: float = Field(default=0.5, gt=0, le=1)
    openalex_rps: float = Field(default=2.0, gt=0, le=2)
    arxiv_interval_s: float = Field(default=3.0, ge=3)
    pdf_daily_limit: int = Field(default=5000, ge=1, le=5000)
    pdf_download_enabled: bool = False
    links_max_batches: int = Field(default=20, ge=1, le=200)
    s2_bulk_queries: list[str] = Field(default_factory=lambda: [
        "language model", "agent", "decoding", "inference", "learning", "planning", "reasoning",
    ], min_length=1, max_length=20)
    openalex_low_yield: int = Field(default=20, ge=0, le=1000)
    alert_email: str = ""
    smtp_host: str = ""
    smtp_port: int = Field(default=465, ge=1, le=65535)
    smtp_user: str = Field(default="", repr=False)
    smtp_pass: str = Field(default="", repr=False)
    user_agent: str = "LitHub-Pavilion/1.3 (personal research; contact:{contact})"
    timezone: str = "Asia/Shanghai"
    log_level: str = "INFO"

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        ZoneInfo(value)
        return value

    @field_validator("dblp_base_url")
    @classmethod
    def valid_dblp_endpoint(cls, value):
        from urllib.parse import urlsplit
        parts = urlsplit(value)
        if parts.scheme != "https" or parts.hostname not in ("dblp.org", "dblp.uni-trier.de") or parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("DBLP_BASE_URL must use an official HTTPS DBLP host")
        if parts.port not in (None, 443) or parts.path not in ("", "/"):
            raise ValueError("DBLP_BASE_URL must be an origin without a custom port/path")
        return value.rstrip("/")

    @field_validator("s2_bulk_queries")
    @classmethod
    def bounded_queries(cls, values):
        if any(not value.strip() or len(value) > 200 for value in values):
            raise ValueError("S2 queries must contain 1–200 characters")
        return list(dict.fromkeys(value.strip() for value in values))

    @property
    def effective_user_agent(self) -> str:
        return self.user_agent.format(contact=self.contact_email or "not-configured")

    @property
    def startup_years(self) -> list[int]:
        end = self.startup_year_to or datetime.now(timezone.utc).year
        return list(range(self.startup_year_from, end + 1))

    @field_validator("startup_year_to", mode="before")
    @classmethod
    def optional_end_year(cls, value):
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("snapshot_dir", "pages_token_file", mode="before")
    @classmethod
    def stable_snapshot_path(cls, value):
        path = Path(value)
        return path if path.is_absolute() else PROJECT_ROOT / path

    @property
    def weekly_years(self) -> list[int]:
        return self.startup_years[-2:]

    @model_validator(mode="after")
    def bounded_startup_range(self):
        if not 1 <= len(self.startup_years) <= 30:
            raise ValueError("Startup collection range must contain 1–30 years")
        if self.pages_publish_enabled and not self.snapshot_enabled:
            raise ValueError("Pages publication requires snapshot export to be enabled")
        return self

    @model_validator(mode="after")
    def apply_rate_tier(self):
        if self.s2_api_key and "s2_rps" not in self.model_fields_set:
            self.s2_rps = 1.0
        return self


settings = Settings()
