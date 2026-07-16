from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # OpenAI — optional for dev/test without LLM
    openai_api_key: str = "sk-dev-placeholder"

    # PostgreSQL — optional, falls back to SQLite when not set
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "aicfo"
    postgres_user: str = "aicfo"
    postgres_password: str = "changeme"

    # If set, overrides the postgres_* fields entirely
    database_url_override: str = ""

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # App
    backend_secret_key: str = "dev-secret-change-in-production"
    backend_cors_origins: str = "http://localhost:3000,http://localhost:3001,http://localhost:3002"

    # Storage
    storage_backend: str = "local"
    storage_local_path: str = "./uploads"

    # LLM — set llm_base_url to use DeepSeek or any OpenAI-compatible API
    llm_model: str = "deepseek-chat"
    llm_temperature: float = 0.0
    llm_max_tokens: int = 16384
    # DeepSeek: https://api.deepseek.com
    # OpenAI:   https://api.openai.com/v1  (or leave empty)
    llm_base_url: str = "https://api.deepseek.com"

    # File upload
    max_upload_size_mb: int = 10

    # Dev mode: use SQLite instead of PostgreSQL
    use_sqlite: bool = True

    @property
    def database_url(self) -> str:
        if self.database_url_override:
            return self.database_url_override
        if self.use_sqlite:
            return "sqlite+aiosqlite:///./aicfo_dev.db"
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_sync(self) -> str:
        if self.use_sqlite:
            return "sqlite:///./aicfo_dev.db"
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.backend_cors_origins.split(",")]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
