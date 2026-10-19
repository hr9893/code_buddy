import re

from langchain.agents.middleware import wrap_tool_call
from langchain_core.messages import ToolMessage

from src.config.settings import settings
from src.guardrails.command_filter import CommandGuardrail

approval_handler = None  # TUI sets this to self.ask_approval; None falls back to console input()

_PUSH = re.compile(r"\bgit\s+push\b", re.I)
_PUSH_BLOCKED = re.compile(r"\bgit\s+push\b.*(\s-f\b|--force|(?<![\w/-])(main|master)(?![\w/-]))", re.I)
_PUSH_ALLOWED = re.compile(r"\bcodepilot/\S+")

_FILE_TOOLS = {"read_file", "write_file", "edit_file", "github_read_file", "create_file", "update_file"}
_WRITE_TOOLS = {"write_file", "edit_file", "create_file", "update_file", "execute"}

def _extract_path(args: dict) -> str:
    """Extract file path from either local or GitHub toolkit tool arguments."""
    for key in ("file_path", "path", "file_query"):
        if val := args.get(key):
            return str(val).splitlines()[0].strip()
    return ""

def violation(tool: str, args: dict) -> str | None:
    """Return the reason a tool call must be blocked, or None if it may proceed."""
    if tool == "execute":
        cmd = args.get("command", "")
        for ok, why in (CommandGuardrail.inspect_command(cmd), CommandGuardrail.inspect_file_path(cmd)):
            if not ok:
                return why
        if _PUSH.search(cmd):
            if _PUSH_BLOCKED.search(cmd):
                return "force pushes and pushes to main/master are not allowed"
            if not _PUSH_ALLOWED.search(cmd):
                return "pushes are only allowed to codepilot/* branches"

    elif tool in _FILE_TOOLS:
        ok, why = CommandGuardrail.inspect_file_path(_extract_path(args))
        if not ok:
            return why

    # Run TypeSafe Jev semantic safety check on code-write and command-execution tools
    if tool in _WRITE_TOOLS:
        ok, why = CommandGuardrail.inspect_with_jev(tool, str(args))
        if not ok:
            return why

    return None

def _approved(action_summary: str) -> bool:
    if settings.auto_approve_push:
        return True
    if approval_handler:
        return approval_handler(action_summary)
    return input(f"\n[approval] agent wants to run: {action_summary}\nApprove? [y/N] ").strip().lower() == "y"

@wrap_tool_call
def guardrails(request, handler):
    call = request.tool_call
    name, args = call["name"], call["args"]
    reason = violation(name, args)

    # Human-in-the-loop gate for git push OR opening a GitHub Pull Request
    if not reason:
        if name == "execute" and _PUSH.search(args.get("command", "")):
            if not _approved(args["command"]):
                reason = "a human rejected this push"
        elif name == "create_pull_request":
            if not _approved(f"Open Pull Request: { str(args)[:120] }"):
                reason = "a human rejected opening this pull request"

    if reason:
        return ToolMessage(
            content=f"BLOCKED: {reason}. Do not retry this; choose another approach or report it.",
            tool_call_id=call["id"],
            name=name,
            status="error",
        )
    return handler(request)