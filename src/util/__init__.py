import json
import logging
from typing import Any

log = logging.getLogger("codepilot")


def add_logger(level: str, message: str, payload: Any = None) -> None:
    """Logs a message along with a pretty-printed payload dictionary or list."""
    log_func = getattr(log, level.lower(), log.info)

    if payload is None:
        log_func(message)
        return

    try:
        if isinstance(payload, (dict, list)):
            formatted_payload = json.dumps(payload, indent=2, default=str)
        else:
            formatted_payload = str(payload)

        log_func("%s\n--- PAYLOAD ---\n%s\n----------------", message, formatted_payload)
    except Exception as e:
        log_func("%s (Failed to format payload: %s)\n%s", message, e, str(payload))