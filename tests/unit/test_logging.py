from __future__ import annotations

import json
import logging

from polyverse.app.logging import JsonLogFormatter, configure_json_logging


def test_json_log_formatter_emits_only_bounded_structured_fields() -> None:
    record = logging.makeLogRecord(
        {
            "name": "polyverse.test",
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
    polyverse_logger = logging.getLogger("polyverse")
    existing_handlers = tuple(polyverse_logger.handlers)
    try:
        configure_json_logging("WARNING")
        configure_json_logging("DEBUG")
        json_handlers = [
            handler
            for handler in polyverse_logger.handlers
            if isinstance(handler.formatter, JsonLogFormatter)
        ]

        assert polyverse_logger.level == logging.DEBUG
        assert len(json_handlers) == 1
        assert json_handlers[0].level == logging.DEBUG
        assert polyverse_logger.propagate is False
    finally:
        polyverse_logger.handlers = list(existing_handlers)
