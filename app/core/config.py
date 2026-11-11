from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_JWT_SECRET = "dev-insecure-secret-change-me-before-deploying"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "GenHealth Order Intake API"
    environment: str = "development"

    database_url: str = "sqlite:///./local.db"

    jwt_secret: str = DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    cors_origins: str = "*"

    openai_api_key: str | None = None
    openai_model: str = "gpt-5.5"
    openai_timeout_seconds: float = 90.0
    openai_reasoning_effort: str | None = "low"

    nppes_lookup_enabled: bool = True
    nppes_timeout_seconds: float = 5.0

    rate_limit_enabled: bool = True
    rate_limit_register_per_minute: int = 5
    rate_limit_login_per_minute: int = 10
    rate_limit_upload_per_minute: int = 10

    max_upload_mb: int = 20
    max_pdf_pages: int = 30

    @field_validator("database_url")
    @classmethod
    def normalize_database_url(cls, v: str) -> str:
        # Render and Heroku-style URLs use the postgres:// scheme; SQLAlchemy needs a driver.
        if v.startswith("postgres://"):
            v = "postgresql://" + v.removeprefix("postgres://")
        if v.startswith("postgresql://"):
            v = "postgresql+psycopg://" + v.removeprefix("postgresql://")
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
