from __future__ import annotations

import pytest
from certificados_backend.services import job_dispatch


class _Response:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _Session:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code
        self.calls: list[tuple[str, dict, int]] = []

    def post(self, url: str, *, json: dict, timeout: int) -> _Response:
        self.calls.append((url, json, timeout))
        return _Response(self.status_code)


RUN_URL = (
    "https://run.googleapis.com/v2/projects/example-project/locations/"
    "southamerica-east1/jobs/certificados-emission-worker:run"
)


def test_resident_mode_does_not_contact_control_plane(monkeypatch):
    monkeypatch.setenv("BATCH_WORKER_DISPATCH_MODE", "resident")
    monkeypatch.delenv("BATCH_WORKER_TRIGGER_URL", raising=False)
    assert job_dispatch.trigger_url() is None
    assert job_dispatch.dispatch() is False


def test_cloud_run_trigger_is_strictly_validated(monkeypatch):
    monkeypatch.setenv("BATCH_WORKER_DISPATCH_MODE", "cloud_run_job")
    monkeypatch.setenv("BATCH_WORKER_TRIGGER_URL", "http://example.test/jobs/x:run")
    with pytest.raises(RuntimeError, match="Cloud Run Jobs"):
        job_dispatch.validate_configuration()
    monkeypatch.setenv("BATCH_WORKER_TRIGGER_URL", RUN_URL)
    job_dispatch.validate_configuration()


def test_dispatch_sends_no_batch_or_participant_data(monkeypatch):
    session = _Session()
    monkeypatch.setenv("BATCH_WORKER_DISPATCH_MODE", "cloud_run_job")
    monkeypatch.setenv("BATCH_WORKER_TRIGGER_URL", RUN_URL)
    monkeypatch.setattr(job_dispatch, "_authorized_session", lambda: session)
    assert job_dispatch.dispatch() is True
    assert session.calls == [(RUN_URL, {}, 10)]


def test_dispatch_failure_keeps_durable_queue_available(monkeypatch):
    session = _Session(status_code=503)
    monkeypatch.setenv("BATCH_WORKER_DISPATCH_MODE", "cloud_run_job")
    monkeypatch.setenv("BATCH_WORKER_TRIGGER_URL", RUN_URL)
    monkeypatch.setattr(job_dispatch, "_authorized_session", lambda: session)
    assert job_dispatch.dispatch() is False
