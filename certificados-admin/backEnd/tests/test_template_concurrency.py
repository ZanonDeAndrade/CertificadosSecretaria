"""PostgreSQL collision tests for immutable template versions."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from database.models import TemplateVersion, TemplateVersionSequence
from database.repositories import CertificateTemplateRepository, TemplateVersionRepository

pytestmark = pytest.mark.postgres


def _create(repo: TemplateVersionRepository, template_id: int, name: str) -> dict:
    return repo.create(
        template_id=template_id,
        name=name,
        layout_json='{"elements":[]}',
        image_width=3508,
        image_height=2480,
        background_image=b"synthetic-image",
        background_mime_type="image/png",
    )


def _model(session, name: str) -> int:  # noqa: ANN001 - SQLAlchemy Session
    return CertificateTemplateRepository(session).create(
        name=name, certificate_type=None, course_id=None, created_by=None
    )


def test_concurrent_creates_receive_distinct_monotonic_versions(postgres_engine):
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False, future=True)
    with factory.begin() as session:
        session.add(TemplateVersionSequence(id=1, next_number=1))
        template_id = _model(session, "Concorrente")
    barrier = Barrier(8)

    def create(index: int) -> int:
        with factory.begin() as session:
            barrier.wait(timeout=10)
            result = _create(TemplateVersionRepository(session), template_id, f"v{index}")
            return int(result["version_number"])

    with ThreadPoolExecutor(max_workers=8) as pool:
        versions = list(pool.map(create, range(8)))
    assert sorted(versions) == list(range(1, 9))


def test_concurrent_activation_leaves_exactly_one_active(postgres_engine):
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False, future=True)
    with factory.begin() as session:
        session.add(TemplateVersionSequence(id=1, next_number=1))
        repo = TemplateVersionRepository(session)
        first = _create(repo, _model(session, "Primeiro"), "primeiro")
        second = _create(repo, _model(session, "Segundo"), "segundo")
        assert repo.activate(int(first["id"]))

    barrier = Barrier(2)

    def activate(version_id: int) -> bool:
        with factory.begin() as session:
            barrier.wait(timeout=10)
            return TemplateVersionRepository(session).activate(version_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(activate, (int(first["id"]), int(second["id"]))))
    assert outcomes == [True, True]
    with factory() as session:
        assert (
            session.execute(
                select(func.count())
                .select_from(TemplateVersion)
                .where(TemplateVersion.is_active == 1)
            ).scalar_one()
            == 1
        )
