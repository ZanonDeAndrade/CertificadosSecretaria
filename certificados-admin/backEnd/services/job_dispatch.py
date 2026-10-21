"""Best-effort wake-up for a durable PostgreSQL queue.

PostgreSQL remains the source of truth.  In Cloud Run, the API starts a Job
execution after committing a new batch; an inexpensive periodic execution is
the fallback if that control-plane request is unavailable.  No participant
data, batch payload or credential is sent to the Jobs API.
"""

from __future__ import annotations

import logging
import os
import re
from urllib.parse import urlsplit

import observability
from database import config as db_config

LOGGER = logging.getLogger("certificados.job_dispatch")
DISPATCH_SUCCEEDED = "emission_job_dispatch_succeeded_total"
DISPATCH_FAILED = "emission_job_dispatch_failed_total"
_RUN_PATH = re.compile(
    r"/v2/projects/[A-Za-z0-9._:-]{1,128}/locations/[a-z0-9-]{1,63}/"
    r"jobs/[a-z0-9-]{1,63}:run"
)


def mode() -> str:
    value = (os.getenv("BATCH_WORKER_DISPATCH_MODE") or "resident").strip().lower()
    if value not in {"resident", "cloud_run_job"}:
        raise RuntimeError("BATCH_WORKER_DISPATCH_MODE deve ser resident ou cloud_run_job.")
    return value


def trigger_url() -> str | None:
    if mode() != "cloud_run_job":
        return None
    value = (os.getenv("BATCH_WORKER_TRIGGER_URL") or "").strip()
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise RuntimeError("BATCH_WORKER_TRIGGER_URL inválida.") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != "run.googleapis.com"
        or port not in {None, 443}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not _RUN_PATH.fullmatch(parsed.path)
    ):
        raise RuntimeError("BATCH_WORKER_TRIGGER_URL deve ser um endpoint Cloud Run Jobs v2 HTTPS.")
    return value


def validate_configuration() -> None:
    selected = mode()
    if selected == "cloud_run_job":
        trigger_url()
    if db_config.is_production() and selected == "resident":
        # A resident worker is valid for Docker Compose; no extra requirement.
        return


def _authorized_session():  # noqa: ANN202 - Google adapter type is optional at import time
    import google.auth
    from google.auth.transport.requests import AuthorizedSession

    credentials, _project = google.auth.default(
        scopes=("https://www.googleapis.com/auth/cloud-platform",)
    )
    return AuthorizedSession(credentials)


def dispatch() -> bool:
    """Start a worker execution without moving queue state out of PostgreSQL."""
    url = trigger_url()
    if not url:
        return False
    try:
        response = _authorized_session().post(url, json={}, timeout=10)
        if not 200 <= int(response.status_code) < 300:
            raise RuntimeError(f"Cloud Run Jobs respondeu HTTP {response.status_code}.")
    except Exception as exc:  # noqa: BLE001 - background wake-up must not lose the batch
        LOGGER.error("event=job_dispatch_failed error_type=%s", type(exc).__name__)
        observability.metrics.increment(DISPATCH_FAILED)
        return False
    observability.metrics.increment(DISPATCH_SUCCEEDED)
    LOGGER.info("event=job_dispatch_succeeded")
    return True
