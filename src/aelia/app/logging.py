from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Final

_STRUCTURED_FIELDS: Final[tuple[str, ...]] = (
    "command",
    "cycle_id",
    "cycle_status",
    "delivery_id",
    "dispatch_outcome",
    "duplicate",
    "error_code",
    "event_id",
    "matched",
    "recovered_count",
)


class JsonLogFormatter(logging.Formatter):
    """Bounded JSON logs; arbitrary record extras are intentionally excluded."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for field in _STRUCTURED_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )


def configure_json_logging(level: str) -> None:
    logger = logging.getLogger("aelia")
    logger.setLevel(level)
    logger.propagate = False
    json_handlers = [
        handler for handler in logger.handlers if isinstance(handler.formatter, JsonLogFormatter)
    ]
    for existing in json_handlers:
        logger.removeHandler(existing)
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(JsonLogFormatter())
    logger.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"aelia.{name}")
