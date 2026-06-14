"""
Structured logging via structlog — wraps stdlib so existing getLogger() calls
automatically emit JSON. Request context (request_id, user_id) bound via
contextvars by the RequestLoggingMiddleware in main.py.
"""
from __future__ import annotations
import logging
import os
import sys
import uuid
from contextvars import ContextVar
from typing import Any

import structlog

_request_id_var: ContextVar[str] = ContextVar("request_id", default="")
_user_id_var:    ContextVar[str] = ContextVar("user_id",    default="")


def get_request_id() -> str:
    return _request_id_var.get()


def set_request_context(request_id: str, user_id: str = "") -> None:
    _request_id_var.set(request_id)
    _user_id_var.set(user_id)


def _add_request_context(
    logger: Any, method: str, event_dict: dict
) -> dict:
    rid = _request_id_var.get()
    uid = _user_id_var.get()
    if rid:
        event_dict["request_id"] = rid
    if uid:
        event_dict["user_id"] = uid
    return event_dict


def configure_logging() -> None:
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _add_request_context,
        structlog.processors.StackInfoRenderer(),
    ]

    use_json = os.getenv("LOG_FORMAT", "json").lower() == "json"

    if use_json:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, log_level, logging.INFO))

    for noisy in ("uvicorn", "apscheduler"): #"uvicorn.access",
        logging.getLogger(noisy).setLevel(logging.WARNING)
