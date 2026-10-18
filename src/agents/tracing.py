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

_MAX_READS_PER_AGENT = 10
_VIRTUAL_FS_TOOLS = {"ls", "glob", "grep"}

class ModelCallLimitExceeded(RuntimeError):
    pass

def _run_timed(label: str, handler, request):
    started = time.monotonic()
    trace_log.info("%s started", label)
    try:
        result = handler(request)
        trace_log.info("%s finished in %.2fs", label, time.monotonic() - started)
        return result
    except Exception:
        trace_log.exception("%s failed after %.2fs", label, time.monotonic() - started)
        raise

def _extract_arg_preview(args: dict) -> str:
    for key in ("file_path", "path", "branch_name", "query", "subagent_type"):
        if val := args.get(key):
            return str(val)[:60]
    if args:
        first_val = next(iter(args.values()))
        return str(first_val)[:60]
    return ""

def trace_model_calls(agent_name: str, call_limit: int):
    call_count = 0

    @wrap_model_call
    def trace_model_call(request, handler):
        nonlocal call_count
        if call_count >= call_limit:
            trace_log.warning("Model call limit reached: agent=%s limit=%d", agent_name, call_limit)
            raise ModelCallLimitExceeded(f"{agent_name} exceeded its {call_limit}-call model budget")

        call_count += 1
        model_name = getattr(request.model, "model_name", None) or getattr(
            request.model, "model", type(request.model).__name__
        )
        label = f"Agent model request: agent={agent_name} call={call_count}/{call_limit} model={model_name}"
        return _run_timed(label, handler, request)

    return trace_model_call

def trace_tool_calls(
    agent_name: str | Callable[[str], None] = "agent",
    on_pull_request_created: Callable[[str], None] | None = None,
):
    if callable(agent_name):
        agent_name, on_pull_request_created = "coder", agent_name

    call_count = 0
    read_count = 0
    seen_reads: set[str] = set()

    @wrap_tool_call
    def trace_tool_call(request, handler):
        nonlocal call_count, read_count
        call_count += 1
        tool_call = request.tool_call
        tool_name = tool_call["name"]
        tool_id = tool_call.get("id", "tool_call")
        args = tool_call.get("args") or {}
        arg_preview = _extract_arg_preview(args)
        tool_label = f"{tool_name}({arg_preview})" if arg_preview else tool_name

        # 1. Block virtual filesystem tools that don't access the remote GitHub repo
        if tool_name in _VIRTUAL_FS_TOOLS:
            trace_log.info("Agent tool blocked (virtual FS): agent=%s tool=%s", agent_name, tool_label)
            return ToolMessage(
                tool_call_id=tool_id,
                content=(
                    f"`{tool_name}` only checks an empty local virtual filesystem, not the GitHub repository. "
                    "Do not call `ls`, `glob`, or `grep`. Use your GitHub tools instead, or if you do not "
                    "know the repository file paths, finish and ask the Orchestrator to run `repo-explorer` first."
                ),
            )

        # 2. Prevent duplicate or runaway github_read_file loops
        if tool_name == "github_read_file":
            norm_path = arg_preview.strip().strip("/").casefold()
            if norm_path and norm_path in seen_reads:
                trace_log.warning("Blocked duplicate read: agent=%s path=%s", agent_name, arg_preview)
                return ToolMessage(
                    tool_call_id=tool_id,
                    content=(
                        f"You already called `github_read_file` on `{arg_preview}` in this session. "
                        "Do not read it again. Use the file contents already in your conversation history "
                        "to call `update_file`, or stop and report to the Orchestrator if you cannot locate the target file."
                    ),
                )
            if read_count >= _MAX_READS_PER_AGENT:
                trace_log.warning("Read limit (%d) reached: agent=%s", _MAX_READS_PER_AGENT, agent_name)
                return ToolMessage(
                    tool_call_id=tool_id,
                    content=(
                        f"STOP: You have reached the maximum of {_MAX_READS_PER_AGENT} `github_read_file` calls. "
                        "Do NOT call `github_read_file` again. Either apply your changes now with `update_file` "
                        "and `create_pull_request`, or return immediately and tell the Orchestrator to dispatch "
                        "`repo-explorer` to find the exact file paths."
                    ),
                )
            if norm_path:
                seen_reads.add(norm_path)
            read_count += 1

        label = f"Agent tool: agent={agent_name} call={call_count} tool={tool_label}"
        result = _run_timed(label, handler, request)

        if tool_name == "create_pull_request" and on_pull_request_created:
            msg = str(getattr(result, "content", result))
            if "successfully created pr" in msg.casefold():
                on_pull_request_created(msg)
        return result

    return trace_tool_call