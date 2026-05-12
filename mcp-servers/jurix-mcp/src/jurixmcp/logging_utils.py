from __future__ import annotations

import json
import logging


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }
        for key in ("event", "email", "status", "article_id", "detail"):
            if hasattr(record, key):
                data[key] = getattr(record, key)
        return json.dumps(data, ensure_ascii=True)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    root = logging.getLogger("jurixmcp")
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(handler)
