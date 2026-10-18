from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # GitHub settings
    github_app_id: str
    github_app_private_key: str
    github_repository: str

    # API Keys (optional here if set in environment, kept for validation/compatibility)
    deepseek_api_key: str | None = None
    groq_api_key: str | None = None
    openai_api_key: str | None = None

    # LiteLLM Model Tiers
    coder_model: str = "deepseek/deepseek-chat"
    fast_model: str = "groq/openai/gpt-oss-120b"
    fallback_model: str = "openai/gpt-4o-mini"

    # LiteLLM Cost & Reliability Controls
    llm_timeout_seconds: int = 60
    llm_max_retries: int = 2
    max_budget_per_issue_usd: float = 0.25
    repo_map_token_budget: int = 4000

    # Runtime & Memory settings
    poll_interval_minutes: int = 5
    auto_approve_push: bool = False
    data_dir: str = "data"
    episodic_lookback_sessions: int = 3

    @property
    def sqlite_path(self) -> Path:
        return Path(self.data_dir) / "codepilot.db"


settings = Settings()
