import logging
import os
import re
from typing import Tuple

log = logging.getLogger("codepilot.guardrails")

FORBIDDEN_COMMAND_PATTERNS = [
    r"\brm\s+-[a-z]*[rf]",                    # rm -rf, rm -fr, rm -r, rm -f
    r"\b(rmdir|rd)\s+/s",                     # Windows: remove directory tree
    r"\bdel\s+/[fsq]",                        # Windows: forced delete
    r"\bRemove-Item\b",                       # PowerShell delete
    r"\b(curl|wget|Invoke-WebRequest|iwr|scp|ssh|nc|ncat)\b",
    r"\b(pip3?|uv)\s+(install|add)\b",
    r"\bnpm\s+(install|i|ci)\b",
]

FORBIDDEN_FILE_PATTERNS = [
    r"(^|[/\\])\.env(\b|\.)",
    r"\.secret\b",
    r"\.pem\b",
    r"\.key\b",
    r"credentials",
]

class GuardrailViolation(Exception):
    """Raised when an operation violates security policy."""

class CommandGuardrail:
    """Enforces regex and TypeSafe Jev semantic safety rules over agent actions."""

    @staticmethod
    def inspect_command(command: str) -> Tuple[bool, str]:
        """Checks if a shell command contains dangerous directives."""
        for pattern in FORBIDDEN_COMMAND_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return False, f"Blocked directive matching pattern: '{pattern}'"
        return True, "Command cleared safety check."

    @staticmethod
    def inspect_file_path(file_path: str) -> Tuple[bool, str]:
        """Checks if a target file path touches protected/sensitive configurations."""
        for pattern in FORBIDDEN_FILE_PATTERNS:
            if re.search(pattern, file_path, re.IGNORECASE):
                return False, f"Blocked target file matching protected pattern: '{pattern}'"
        return True, "File path cleared safety check."

    @staticmethod
    def inspect_with_jev(tool_name: str, payload: str, threshold: float = 0.85) -> Tuple[bool, str]:
        """Uses TypeSafe Jev Noul primitives to detect semantic risk or hardcoded secrets."""
        api_key = os.environ.get("TYPESAFE_API_KEY")
        if not api_key or not payload.strip():
            return True, "Jev check skipped (no key or empty payload)."

        try:
            from typesafe_sdk import Noul, TypeSafeClient

            with TypeSafeClient(api_key=api_key) as client:
                res = client.system_one(
                    state={"tool": tool_name, "payload": payload[:4000]},
                    questions={
                        "destructive": Noul(
                            instructions=(
                                "Does this action attempt to delete repository history, "
                                "exfiltrate secrets over the network, or introduce a malicious backdoor?"
                            )
                        ),
                        "leaks_secret": Noul(
                            instructions=(
                                "Does this payload contain a real hardcoded API key, private RSA key, "
                                "or password string (excluding env var references like os.environ)?"
                            )
                        ),
                    },
                )
            p_dest = res.nouls["destructive"].noul
            p_leak = res.nouls["leaks_secret"].noul
            if p_dest >= threshold:
                return False, f"Jev blocked destructive/exfiltration risk (score={p_dest:.2f})"
            if p_leak >= threshold:
                return False, f"Jev blocked potential hardcoded secret leak (score={p_leak:.2f})"
        except Exception as exc:
            log.debug("Jev guardrail check skipped: %s", exc)

        return True, "Cleared Jev safety check."