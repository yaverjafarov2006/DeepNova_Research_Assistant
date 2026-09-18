"""Central logging configuration.

The level is driven by `LOG_LEVEL` (via `Settings`). Logs go to stderr so the
CLI can keep stdout clean for the answer itself — that makes
`python -m researcher ask "..." --json | jq` work.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

_CONFIGURED = False


class JsonFormatter(logging.Formatter):
    """One JSON object per line — handy when logs go to a collector."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key.startswith("ctx_"):
                payload[key[4:]] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str = "INFO", *, json_output: bool = False, force: bool = False) -> None:
    """Configure the root logger once per process."""
    global _CONFIGURED
    if _CONFIGURED and not force:
        return

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stderr)
    if json_output:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s | %(levelname)-7s | %(name)-28s | %(message)s",
                datefmt="%H:%M:%S",
            )
        )
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # httpx logs every request at INFO — too chatty for our output.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
