"""Application configuration loaded from environment variables and ``.env``."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from poster_agent.domain.errors import ConfigurationError


class Settings(BaseSettings):
    """Typed runtime settings.

    Empty OpenAI values are accepted at startup so commands such as ``doctor`` and
    checkpoint inspection can run offline. ``require_openai`` protects API commands.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "development"
    log_level: str = "INFO"
    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = ""
    openai_embedding_model: str = "text-embedding-3-small"
    openai_image_model: str = "gpt-image-2.5-flare"
    openai_timeout_seconds: float = 60.0
    artifacts_dir: Path = Path("artifacts")
    checkpoint_db_path: Path = Path("data/checkpoints.db")
    brand_knowledge_db_path: Path = Path("data/brand_knowledge.db")
    rag_chunk_size: int = 1200
    rag_chunk_overlap: int = 200
    rag_top_k: int = 6
    poster_variant_count: int = 3
    poster_max_render_attempts: int = 2
    poster_qa_threshold: int = 75
    poster_generation_size: str = "1088x1360"
    poster_generation_quality: str = "high"
    database_url: str = "sqlite+aiosqlite:///./data/poster_agent.db"

    def require_openai(self) -> None:
        """Raise a safe error when an API-backed command is not configured."""

        if not self.openai_api_key.get_secret_value().strip():
            raise ConfigurationError("OPENAI_API_KEY is missing from .env")
        if not self.openai_model.strip():
            raise ConfigurationError("OPENAI_MODEL is missing from .env")
        if not self.openai_embedding_model.strip():
            raise ConfigurationError("OPENAI_EMBEDDING_MODEL is missing from .env")

    def require_image_openai(self) -> None:
        """Raise a safe error when Sprint 3 image generation is not configured."""

        if not self.openai_api_key.get_secret_value().strip():
            raise ConfigurationError("OPENAI_API_KEY is missing from .env")
        if not self.openai_model.strip():
            raise ConfigurationError("OPENAI_MODEL is missing from .env")
        if not self.openai_image_model.strip():
            raise ConfigurationError("OPENAI_IMAGE_MODEL is missing from .env")

    def prepare_local_directories(self) -> None:
        """Create local runtime directories without touching their contents."""

        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.brand_knowledge_db_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return one immutable-in-practice settings object per process."""

    return Settings()
