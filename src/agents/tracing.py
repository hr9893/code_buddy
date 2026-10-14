import logging
import time
from collections.abc import Callable

from langchain.agents.middleware import wrap_model_call, wrap_tool_call
from langchain_core.messages import ToolMessage

trace_log = logging.getLogger("codepilot.agent_trace")

MODEL_CALL_LIMITS = {
    "simple": {"repo-explorer": 3, "coder": 8, "pr-agent": 4},
    "moderate": {"repo-explorer": 8, "coder": 16, "pr-agent": 8},
    "complex": {"repo-explorer": 12, "coder": 24, "pr-agent": 12},
}


class ModelCallLimitExceeded(RuntimeError):
    pass


def trace_model_calls(agent_name: str, call_limit: int):
    call_count = 0

    @wrap_model_call
    def trace_model_call(request, handler):
        nonlocal call_count
        if call_count >= call_limit:
            trace_log.warning(
                "Model call limit reached: agent=%s limit=%d",
                agent_name,
                call_limit,
            )
            raise ModelCallLimitExceeded(
                f"{agent_name} exceeded its {call_limit}-call model budget"
            )
        call_count += 1
        model = request.model
        model_name = getattr(model, "model_name", None) or getattr(
            model, "model", type(model).__name__
        )
        started = time.monotonic()
        trace_log.info(
            "Agent model request started: agent=%s call=%d/%d model=%s",
            agent_name,
            call_count,
            call_limit,
            model_name,
        )
        try:
            response = handler(request)
        except Exception:
            trace_log.exception(
                "Agent model request failed: agent=%s model=%s duration=%.2fs",
                agent_name,
                model_name,
                time.monotonic() - started,
            )
            raise
        trace_log.info(
            "Agent model response received: agent=%s model=%s duration=%.2fs",
            agent_name,
            model_name,
            time.monotonic() - started,
        )
        return response

    return trace_model_call


def trace_tool_calls(
    agent_name: str, on_pull_request_created: Callable[[str], None] | None = None
):
    call_count = 0

    @wrap_tool_call
    def trace_tool_call(request, handler):
        nonlocal call_count
        call_count += 1
        tool_name = request.tool_call["name"]
        started = time.monotonic()
        trace_log.info(
            "Agent tool started: agent=%s call=%d tool=%s",
            agent_name,
            call_count,
            tool_name,
        )
        try:
            result = handler(request)
        except Exception:
            trace_log.exception(
                "Agent tool failed: agent=%s call=%d tool=%s duration=%.2fs",
                agent_name,
                call_count,
                tool_name,
                time.monotonic() - started,
            )
            raise
        trace_log.info(
            "Agent tool returned: agent=%s call=%d tool=%s duration=%.2fs",
            agent_name,
            call_count,
            tool_name,
            time.monotonic() - started,
        )
        if tool_name == "create_pull_request" and on_pull_request_created:
            content = result.content if isinstance(result, ToolMessage) else str(result)
            message = content if isinstance(content, str) else str(content)
            if "successfully created pr" in message.casefold():
                on_pull_request_created(message)
        return result

    return trace_tool_call
