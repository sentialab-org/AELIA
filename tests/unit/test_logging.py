from __future__ import annotations

import json
import logging

from aelia.app.logging import JsonLogFormatter, configure_json_logging


def test_json_log_formatter_emits_only_bounded_structured_fields() -> None:
    record = logging.makeLogRecord(
        {
            "name": "aelia.test",
            "levelno": logging.INFO,
            "levelname": "INFO",
            "msg": "cycle_processed",
            "cycle_id": "cycle-001",
            "event_id": "event-001",
            "content": "private message content",
        }
    )

    payload = json.loads(JsonLogFormatter().format(record))

    assert payload["event"] == "cycle_processed"
    assert payload["cycle_id"] == "cycle-001"
    assert payload["event_id"] == "event-001"
    assert "private message content" not in json.dumps(payload)
    assert "content" not in payload


def test_logging_configuration_is_idempotent_and_honors_level() -> None:
    aelia_logger = logging.getLogger("aelia")
    existing_handlers = tuple(aelia_logger.handlers)
    try:
        configure_json_logging("WARNING")
        configure_json_logging("DEBUG")
        json_handlers = [
            handler
            for handler in aelia_logger.handlers
            if isinstance(handler.formatter, JsonLogFormatter)
        ]

        assert aelia_logger.level == logging.DEBUG
        assert len(json_handlers) == 1
        assert json_handlers[0].level == logging.DEBUG
        assert aelia_logger.propagate is False
    finally:
        aelia_logger.handlers = list(existing_handlers)
