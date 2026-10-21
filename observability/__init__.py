"""Shared observability for both apps: structured JSON logs, request
correlation ids, and lightweight in-process metrics.

Privacy: logs and metrics carry **no personal data** — only opaque job/request
identifiers, counters, status, durations and the request path (never the query
string, which could contain a searched name). Import-safe; depends only on the
stdlib + Starlette (already a FastAPI dependency).
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections import defaultdict
from contextvars import ContextVar
from datetime import datetime, timezone
from threading import Lock

from starlette.middleware.base import BaseHTTPMiddleware

# ── Correlation id ──────────────────────────────────────────────────────────────

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="-")
_SAFE_CORRELATION_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")


def new_correlation_id() -> str:
    return uuid.uuid4().hex


def get_correlation_id() -> str:
    return correlation_id_var.get()


# ── Structured JSON logging ─────────────────────────────────────────────────────


class _CorrelationFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        record.correlation_id = correlation_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", "-"),
        }
        for key, value in getattr(record, "structured", {}).items():
            payload[key] = value
        if record.exc_info and record.exc_info[0]:
            # Exception messages/tracebacks may contain provider paths, query
            # values or participant input. Retain the class for triage without
            # copying those values into centralized logs.
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=False)


_configured = False


def configure_logging(level: int = logging.INFO) -> None:
    """Install JSON structured logging on the root logger (idempotent)."""
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(_CorrelationFilter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    _configured = True


def log_event(logger_name: str, message: str, level: int = logging.INFO, **fields) -> None:
    """Emit a structured event (no PII — pass codes/counters, not names)."""
    logging.getLogger(logger_name).log(level, message, extra={"structured": fields})


# ── Metrics (in-process counters) ───────────────────────────────────────────────

# Canonical metric names.
CERTS_GENERATED = "certificates_generated_total"
CERTS_DUPLICATE = "certificates_duplicate_total"
CERTS_FAILED = "certificates_failed_total"
CERTS_COMPENSATED = "certificates_compensated_total"
CERT_DOWNLOADS = "certificate_downloads_total"
INTEGRITY_INCIDENTS = "integrity_incidents_total"
EMISSION_JOBS_COMPLETED = "emission_jobs_completed_total"
EMISSION_JOBS_FAILED = "emission_jobs_failed_total"
EMISSION_JOB_DURATION_MS = "emission_job_duration_ms"
REQUEST_DURATION_MS = "request_duration_ms"
RECONCILIATION_ERRORS = "reconciliation_errors_total"
BACKUPS_COMPLETED = "backups_completed_total"
BACKUPS_FAILED = "backups_failed_total"
RESTORE_DRILLS_COMPLETED = "restore_drills_completed_total"
RESTORE_DRILLS_FAILED = "restore_drills_failed_total"


class _Metrics:
    def __init__(self) -> None:
        self._counters: dict[str, int] = defaultdict(int)
        self._lock = Lock()

    def increment(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[name] += amount
        # Log-based metrics are the durable/multi-worker source. The in-process
        # snapshot remains a cheap diagnostic endpoint only.
        log_event(
            "certificados.metrics",
            "metric",
            metric=name,
            metric_kind="counter_delta",
            value=amount,
        )

    def observe(self, name: str, value: int | float) -> None:
        log_event(
            "certificados.metrics",
            "metric",
            metric=name,
            metric_kind="distribution_sample",
            value=round(float(value), 3),
        )

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counters)

    def reset(self) -> None:  # pragma: no cover - used by tests
        with self._lock:
            self._counters.clear()


metrics = _Metrics()


# ── Request middleware ──────────────────────────────────────────────────────────


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Assign/propagate ``X-Request-ID`` and log each request (no query string)."""

    async def dispatch(self, request, call_next):
        supplied = (request.headers.get("X-Request-ID") or "").strip()
        # X-Request-ID is client-controlled. Restrict it before reflecting it
        # into response headers and every structured log record.
        cid = supplied if _SAFE_CORRELATION_ID.fullmatch(supplied) else new_correlation_id()
        token = correlation_id_var.set(cid)
        started = time.monotonic()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = cid
            return response
        finally:
            duration_ms = round((time.monotonic() - started) * 1000, 2)
            log_event(
                "certificados.access",
                "request",
                method=request.method,
                path=request.url.path,  # path only — never the query (may hold a name)
                status=status,
                duration_ms=duration_ms,
            )
            metrics.observe(REQUEST_DURATION_MS, duration_ms)
            correlation_id_var.reset(token)
