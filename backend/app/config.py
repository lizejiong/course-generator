from pathlib import Path

from pydantic import PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: PostgresDsn
    courses_root: Path = Path("courses")
    releases_root: Path = Path("releases")
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4.1-mini"
    tavily_api_key: str | None = None
    log_level: str = "INFO"

    def prepare_paths(self) -> None:
        self.courses_root.mkdir(parents=True, exist_ok=True)
        self.releases_root.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    return Settings()
