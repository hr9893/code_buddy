from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    github_app_id: str
    github_app_private_key: str
    github_repository: str
    deepseek_api_key: str
    poll_interval_minutes: int = 5
    auto_approve_push: bool = False

    data_dir: Path = Path("data")
    episodic_lookback_sessions: int = 3  # past sessions checked for failed issues

    @property
    def sqlite_path(self) -> str:
        return str(self.data_dir / "codepilot.db")

settings = Settings()
