import re
from typing import Tuple

# NOTE: `git push` is deliberately NOT here. The PR agent must be able to push a codepilot/* branch,
# so push rules (branch name, no force, human approval) live in middleware.py instead.
FORBIDDEN_COMMAND_PATTERNS = [
    r"\brm\s+-[a-z]*[rf]",                    # rm -rf, rm -fr, rm -r, rm -f
    r"\b(rmdir|rd)\s+/s",                     # Windows: remove directory tree
    r"\bdel\s+/[fsq]",                        # Windows: forced delete
    r"\bRemove-Item\b",                       # PowerShell delete
    r"\b(curl|wget|Invoke-WebRequest|iwr|scp|ssh|nc|ncat)\b",
    r"\b(pip3?|uv)\s+(install|add)\b",
    r"\bnpm\s+(install|i|ci)\b",
]

# Matched anywhere in the text, so they work for file paths AND for shell commands that mention a secret.
FORBIDDEN_FILE_PATTERNS = [
    r"\.env\b",
    r"\.secret\b",
    r"\.pem\b",
    r"\.key\b",
    r"credentials",
]


class GuardrailViolation(Exception):
    """Raised when an operation violates security policy."""


class CommandGuardrail:
    """Interprets and enforces safety rules over sandbox actions."""

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