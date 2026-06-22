"""PostgreSQL integration tests.

These exercise the repository layer against a REAL PostgreSQL instance, proving
the SQLite dev/test backend does not hide PostgreSQL incompatibilities.

They are skipped unless ``TEST_DATABASE_URL`` points at a disposable PostgreSQL
database, e.g.::

    TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/certificados_test \\
        python -m pytest tests/test_integration_postgres.py -q

The tables are created and dropped around each run, so the target database must
be safe to mutate.
"""
from __future__ import annotations

import os

import pytest

from database import config as db_config

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL não definido — testes de integração PostgreSQL ignorados.",
)


@pytest.fixture
def pg_session():
    from sqlalchemy import create_engine
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import sessionmaker

    from database.models import Base

    url = db_config.normalize_database_url(TEST_DATABASE_URL)
    if not url.startswith("postgresql"):
        pytest.skip("TEST_DATABASE_URL não é um PostgreSQL.")

    engine = create_engine(url, future=True, **db_config.pool_settings())
    try:
        with engine.connect():
            pass
    except OperationalError as exc:  # server unreachable → skip, don't fail
        engine.dispose()
        pytest.skip(f"PostgreSQL indisponível: {exc}")

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    s = factory()
    try:
        yield s
    finally:
        s.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def _cert(code: str, **over) -> dict:
    base = {
        "unique_code": code,
        "participant_name": "Ana Souza",
        "event_name": "Semana Jurídica",
        "course_name": "Direito",
        "issue_date": "10 de junho de 2026",
        "business_key": code.lower(),
        "template_used": "default",
    }
    base.update(over)
    return base


def test_pg_pool_is_configured(pg_session):
    from sqlalchemy.pool import QueuePool

    bind = pg_session.get_bind()
    assert isinstance(bind.pool, QueuePool)  # real connection pool, not NullPool


def test_pg_crud_roundtrip(pg_session):
    from database.repositories import CertificateRepository

    repo = CertificateRepository(pg_session)
    repo.insert_many([_cert("CERT-2026-PG0001")])
    pg_session.commit()

    row = repo.get_by_code("cert-2026-pg0001")  # case-insensitive on PG too
    assert row is not None
    assert row["template_used"] == "default"
    assert row["drive_file_id"] is None

    repo.set_drive_metadata(
        "CERT-2026-PG0001",
        drive_file_id="drv-pg",
        drive_folder_id="fld",
        original_filename="ana.pdf",
        mime_type="application/pdf",
        file_size=10,
        checksum_sha256="abc",
    )
    pg_session.commit()
    assert repo.get_by_code("CERT-2026-PG0001")["storage_provider"] == "google_drive"


def test_pg_business_key_uniqueness_is_enforced(pg_session):
    """On PostgreSQL the UNIQUE index — not an out-of-transaction check — enforces
    business_key uniqueness: a duplicate insert RAISES (no INSERT OR IGNORE)."""
    from sqlalchemy.exc import IntegrityError

    from database.repositories import CertificateRepository

    repo = CertificateRepository(pg_session)
    repo.insert_many([_cert("CERT-2026-PG0002", business_key="dup")])
    pg_session.commit()

    with pytest.raises(IntegrityError):
        repo.insert_many([_cert("CERT-2026-PG0003", business_key="dup")])  # same key
    pg_session.rollback()

    _rows, total = repo.list()
    assert total == 1
