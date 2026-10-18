import logging
import os
import time
import warnings
from typing import Any, Literal

import litellm
from langchain_litellm import ChatLiteLLM
from litellm.litellm_core_utils.logging_worker import GLOBAL_LOGGING_WORKER
from pydantic import Field

from src.config.settings import settings

# 1. Silence LiteLLM debug banners and benign Pydantic v2 serializer warnings
litellm.suppress_debug_info = True
litellm.turn_off_message_logging = True
litellm.drop_params = True
logging.getLogger("LiteLLM").setLevel(logging.CRITICAL)
logging.getLogger("LiteLLM Router").setLevel(logging.CRITICAL)
warnings.filterwarnings("ignore", message="Pydantic serializer warnings", category=UserWarning)

# 2. Prevent GLOBAL_LOGGING_WORKER from spawning orphaned asyncio tasks
def _noop_enqueue(coro) -> None:
    if hasattr(coro, "close"):
        coro.close()

GLOBAL_LOGGING_WORKER.ensure_initialized_and_enqueue = _noop_enqueue
GLOBAL_LOGGING_WORKER.enqueue = _noop_enqueue

log = logging.getLogger("codepilot.llm")

ModelRole = Literal["coder", "fast"]

# Track rate-limited/exhausted models -> monotonic timestamp when cooldown expires
_MODEL_COOLDOWN_UNTIL: dict[str, float] = {}
_COOLDOWN_SECONDS = 60.0

_DEFAULT_FAST_MODELS = [
    "groq/openai/gpt-oss-120b",
    "groq/openai/gpt-oss-20b",
    "groq/qwen/qwen3.8-27b",
    "deepseek/deepseek-chat",
]

_DEFAULT_CODER_MODELS = [
    "deepseek/deepseek-chat",
    "groq/openai/gpt-oss-120b",
    "groq/qwen/qwen3.8-27b",
    "groq/openai/gpt-oss-20b",
]

def _sync_api_keys() -> None:
    """Export configured API keys from Pydantic settings to os.environ for LiteLLM."""
    for env_key, val in [
        ("DEEPSEEK_API_KEY", getattr(settings, "deepseek_api_key", None)),
        ("GROQ_API_KEY", getattr(settings, "groq_api_key", None)),
        ("OPENAI_API_KEY", getattr(settings, "openai_api_key", None)),
        ("GEMINI_API_KEY", getattr(settings, "gemini_api_key", None)),
    ]:
        if val and not os.environ.get(env_key):
            os.environ[env_key] = val

def _normalize_model_name(model_name: str) -> str:
    """Ensure Groq model IDs always carry the 'groq/' provider prefix for LiteLLM."""
    m = model_name.strip()
    if m in ("groq/llama-3.3-70b-versatile", "llama-3.3-70b-versatile"):
        return "groq/openai/gpt-oss-120b"
    if m in ("groq/llama-3.1-8b-instant", "llama-3.1-8b-instant"):
        return "groq/openai/gpt-oss-20b"
    # Bare Groq Console IDs (e.g. 'openai/gpt-oss-20b' or 'qwen/qwen3.8-27b')
    if m.startswith(("openai/gpt-oss-", "qwen/", "meta-llama/")):
        return f"groq/{m}"
    return m

def _get_key_for_model(model_name: str) -> str | None:
    """Return the API key string for the model's provider."""
    _sync_api_keys()
    provider = model_name.split("/", 1)[0].lower()
    key_map = {
        "deepseek": "DEEPSEEK_API_KEY",
        "groq": "GROQ_API_KEY",
        "openai": "OPENAI_API_KEY",
        "gemini": "GEMINI_API_KEY",
    }
    env_var = key_map.get(provider)
    return os.environ.get(env_var) if env_var else None

def _get_candidate_models(role: ModelRole) -> list[str]:
    """Return ordered list of models for the role whose API keys are configured."""
    if role == "coder":
        configured = getattr(settings, "coder_models", None) or [
            getattr(settings, "coder_model", "deepseek/deepseek-chat"),
            *_DEFAULT_CODER_MODELS,
        ]
    else:
        configured = getattr(settings, "fast_models", None) or [
            getattr(settings, "fast_model", "groq/openai/gpt-oss-120b"),
            *_DEFAULT_FAST_MODELS,
        ]

    normalized = [_normalize_model_name(m) for m in configured if m]
    available = [m for m in dict.fromkeys(normalized) if _get_key_for_model(m)]
    return available or ["deepseek/deepseek-chat"]

class FallbackChatLiteLLM(ChatLiteLLM):
    """ChatLiteLLM subclass that rotates across candidate_models inside completion_with_retry."""

    candidate_models: list[str] = Field(default_factory=list)

    def completion_with_retry(self, run_manager: Any = None, **kwargs: Any) -> Any:
        now = time.monotonic()
        candidates = self.candidate_models or [self.model]

        # Try non-cooled-down models first, keeping cooled-down models as fallback
        active = [m for m in candidates if _MODEL_COOLDOWN_UNTIL.get(m, 0.0) <= now]
        cooled = [m for m in candidates if _MODEL_COOLDOWN_UNTIL.get(m, 0.0) > now]
        ordered = active + cooled

        last_exc: Exception | None = None
        for idx, candidate in enumerate(ordered):
            call_kwargs = dict(kwargs)
            call_kwargs["model"] = candidate
            call_kwargs["api_key"] = _get_key_for_model(candidate)
            call_kwargs["num_retries"] = 0  # Failover immediately instead of sleeping on 429
            call_kwargs.pop("api_base", None)

            try:
                if idx > 0:
                    log.info("Using fallback model: %s", candidate)
                return litellm.completion(**call_kwargs)
            except Exception as exc:
                last_exc = exc
                _MODEL_COOLDOWN_UNTIL[candidate] = time.monotonic() + _COOLDOWN_SECONDS
                next_model = ordered[idx + 1] if idx + 1 < len(ordered) else None
                if next_model:
                    log.warning(
                        "Model %s failed (%s); cooling down %.0fs and switching to %s",
                        candidate,
                        type(exc).__name__,
                        _COOLDOWN_SECONDS,
                        next_model,
                    )
                else:
                    log.error("All candidate models failed; last tried: %s", candidate)
        raise last_exc  # type: ignore[misc]

def get_model(role: ModelRole = "fast") -> FallbackChatLiteLLM:
    """Return a FallbackChatLiteLLM instance that rotates across available models."""
    candidates = _get_candidate_models(role)
    return FallbackChatLiteLLM(
        model=candidates[0],
        candidate_models=candidates,
        temperature=0,
        request_timeout=getattr(settings, "llm_timeout_seconds", 60),
        max_retries=0,
        disable_streaming=True,  # Force synchronous _generate path in LangGraph
    )

def count_tokens(text: str, role: ModelRole = "fast") -> int:
    """Universal token counter across DeepSeek, Groq, and OpenAI."""
    candidates = _get_candidate_models(role)
    return litellm.token_counter(model=candidates[0], text=text)