"""Runtime factories shared by the API composition root and job workers."""

from __future__ import annotations

from pathlib import Path

from certificados_backend.services import settings_service
from certificados_backend.services.certificate_service import (
    CertificateBatchConfig,
    CertificateBatchService,
)
from certificados_backend.services.generator import (
    CertificateGenerator,
    CertificateGeneratorConfig,
)

from database.db import PDFS_DIR

_BACKEND_DIR = Path(__file__).resolve().parent.parent


def build_layout_generator(snapshot: dict | None = None) -> CertificateGenerator:
    """Generator used to measure text and resolve values, without storage.

    Line breaks depend on the bundled fonts alone; the optional institutional
    ``snapshot`` makes it resolve the same values the PDF will print.
    """
    snapshot = snapshot or {}
    return CertificateGenerator(
        CertificateGeneratorConfig(
            template_path=_BACKEND_DIR / "templates" / "certificado_base.png",
            regular_font_path=_BACKEND_DIR / "fonts" / "times.ttf",
            bold_font_path=_BACKEND_DIR / "fonts" / "timesbd.ttf",
            output_dir=PDFS_DIR,
            institution_name=str(snapshot.get("institution_name") or ""),
            issue_location=str(snapshot.get("issue_location") or ""),
            signatory_name=str(snapshot.get("signatory_name") or ""),
            signatory_title=str(snapshot.get("signatory_title") or ""),
        )
    )


def build_certificate_service() -> CertificateBatchService:
    settings = settings_service.serialize(settings_service.ensure_settings())
    return CertificateBatchService(
        CertificateBatchConfig(
            template_path=_BACKEND_DIR / "templates" / "certificado_base.png",
            regular_font_path=_BACKEND_DIR / "fonts" / "times.ttf",
            bold_font_path=_BACKEND_DIR / "fonts" / "timesbd.ttf",
            output_dir=PDFS_DIR,
            issue_location=settings["issue_location"],
            signatory_name=settings["signatory_name"],
            signatory_title=settings["signatory_title"],
            institution_name=settings["institution_name"],
            public_validation_base_url=settings["public_url"],
        )
    )
