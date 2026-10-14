from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from src.config.settings import settings

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"


def get_model() -> BaseChatModel:
    """Create the shared DeepSeek model used by the orchestrator and all agents."""
    return ChatOpenAI(
        model=DEEPSEEK_MODEL,
        api_key=settings.deepseek_api_key,
        base_url=DEEPSEEK_BASE_URL,
        temperature=0,
        timeout=60,
        max_retries=0,
    )
