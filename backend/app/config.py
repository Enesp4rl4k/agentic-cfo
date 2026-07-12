from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # OpenAI
    openai_api_key: str

    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "aicfo"
    postgres_user: str = "aicfo"
    postgres_password: str = "changeme"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # App
    backend_secret_key: str = "dev-secret-change-in-production"
    backend_cors_origins: str = "http://localhost:3000"

    # Storage
    storage_backend: str = "local"
    storage_local_path: str = "./uploads"

    # LLM
    llm_model: str = "gpt-4o"
    llm_temperature: float = 0.0
    llm_max_tokens: int = 16384

    # File upload
    max_upload_size_mb: int = 10

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_sync(self) -> str:
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
