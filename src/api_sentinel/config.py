from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")
    database_url: str = (
        "postgresql+asyncpg://sentinel_app:sentinel-read-local-only@postgres/sentinel"
    )
    redis_url: str = "redis://redis:6379/0"
    cache_redis_url: str = "redis://redis:6379/1"
    erp_url: str = "http://erp:8080"
    secrets_dir: Path = Path("/secrets")
    trace_endpoint: str = "http://jaeger:4318/v1/traces"
    trace_sample_ratio: float = Field(default=0.25, ge=0, le=1)
    sentinel_env: Literal["demo", "test"] = "demo"
    cache_ttl: int = Field(default=15, ge=1, le=300)
    entry_limit: int = Field(default=48, ge=1, le=48)
    authentication_limit: int = Field(default=8, ge=1, le=8)
    tenant_limit: int = Field(default=8, ge=1, le=16)
    business_limit: int = Field(default=16, ge=1, le=16)

    @model_validator(mode="after")
    def validate_capacity(self) -> "Settings":
        if not self.tenant_limit <= self.business_limit <= self.entry_limit:
            raise ValueError("Os limites devem respeitar tenant <= negócio <= entrada.")
        return self

    def cursor_secret(self) -> str:
        value = (self.secrets_dir / "cursor-key").read_text(encoding="utf-8").strip()
        if len(value) < 32 or len(value) > 512 or not value.isascii():
            raise ValueError("O segredo do cursor deve ter entre 32 e 512 caracteres ASCII.")
        return value
