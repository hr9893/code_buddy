import re

from langchain.agents.middleware import wrap_tool_call
from langchain_core.messages import ToolMessage

from src.config.settings import settings
from src.guardrails.command_filter import CommandGuardrail

approval_handler = None   # the TUI sets this to show an approval dialog; None falls back to the console

_PUSH = re.compile(r"\bgit\s+push\b", re.I)
_PUSH_FORCE = re.compile(r"\bgit\s+push\b.*(\s-f\b|--force)", re.I)
_PUSH_PROTECTED = re.compile(r"\bgit\s+push\b.*(?<![\w/-])(main|master)(?![\w/-])", re.I)
_PUSH_ALLOWED = re.compile(r"\bcodepilot/\S+")
_FILE_TOOLS = {"read_file", "write_file", "edit_file"}


def violation(tool: str, args: dict) -> str | None:
    """Return the reason a tool call must be blocked, or None if it may proceed."""
    if tool == "execute":
        cmd = args.get("command", "")
        for ok, why in (CommandGuardrail.inspect_command(cmd),
                        CommandGuardrail.inspect_file_path(cmd)):   # commands that mention a secret file
            if not ok:
                return why
        if _PUSH.search(cmd):
            if _PUSH_FORCE.search(cmd) or _PUSH_PROTECTED.search(cmd):
                return "force pushes and pushes to main/master are not allowed"
            if not _PUSH_ALLOWED.search(cmd):
                return "pushes are only allowed to codepilot/* branches"
    elif tool in _FILE_TOOLS:
        ok, why = CommandGuardrail.inspect_file_path(args.get("file_path", ""))
        if not ok:
            return why
    return None


def _approved(command: str) -> bool:
    if settings.auto_approve_push:
        return True
    if approval_handler:
        return approval_handler(command)
    return input(f"\n[approval] agent wants to run: {command}\nApprove? [y/N] ").strip().lower() == "y"


@wrap_tool_call
def guardrails(request, handler):
    call = request.tool_call
    name, args = call["name"], call["args"]
    reason = violation(name, args)
    if not reason and name == "execute" and _PUSH.search(args.get("command", "")) and not _approved(args["command"]):
        reason = "a human rejected this push"
    if reason:
        return ToolMessage(content=f"BLOCKED: {reason}. Do not retry this; choose another approach or report it.",
                           tool_call_id=call["id"], name=name, status="error")
    return handler(request)