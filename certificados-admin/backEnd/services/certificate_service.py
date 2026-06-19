from __future__ import annotations

import sys
from pathlib import Path as _Path

# When this file is executed directly (python backEnd/services/certificate_service.py),
# Python puts backEnd/services/ on sys.path, which is one level too deep for
# bare imports like "from models import ...".  We always want backEnd/ on the path.
_BACKEND_DIR = str(_Path(__file__).resolve().parent.parent)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from dataclasses import dataclass
from pathlib import Path
from typing import IO

from models import CertificateFormData, Participant, ParticipantRegistryRecord
from services.certificate_store import allocate_codes, save_certificates
from services.generator import (
    CertificateGenerator,
    CertificateGeneratorConfig,
    build_pdf_filename,
)
from services.reader import read_participants
from services.registry import enrich_with_registry
from services.spreadsheet import SpreadsheetRow, compute_business_key
from utils.dates import normalize_date_text
from utils.template_store import get_template_for_course

# certificate_store (imported above) puts the repo root on sys.path, so the
# shared storage layer / database resolve here regardless of the working dir.
from storage_service import CertificateStorage, get_storage
from storage_service import config as storage_config
from database import db


@dataclass(slots=True, frozen=True)
class CertificateBatchConfig:
    template_path: Path
    regular_font_path: Path
    bold_font_path: Path
    output_dir: Path
    file_url_prefix: str = "/certificates"
    # Institution/signatory data — provided via env (see main.create_app).
    issue_location: str = ""
    signatory_name: str = ""
    signatory_title: str = ""


@dataclass(slots=True, frozen=True)
class GeneratedCertificateResult:
    name: str
    file_url: str
    livro: int
    folha: int
    linha: int
    validation_code: str = ""
    # Path of the saved PDF, relative to STORAGE_DIR (e.g. "pdfs/Joao_CERT-2026-AB1234.pdf").
    pdf_path: str = ""


@dataclass(slots=True, frozen=True)
class GenerationSummary:
    """Outcome of a confirmed batch generation (new model)."""

    generated: list[dict]    # [{"name", "code"}]
    duplicates: list[dict]   # [{"name", "existing_code"}]
    total_valid: int


class CertificateBatchService:
    def __init__(
        self,
        config: CertificateBatchConfig,
        storage: CertificateStorage | None = None,
        generator: CertificateGenerator | None = None,
    ) -> None:
        self.config = config
        self.generator = generator or CertificateGenerator(
            CertificateGeneratorConfig(
                template_path=config.template_path,
                regular_font_path=config.regular_font_path,
                bold_font_path=config.bold_font_path,
                output_dir=config.output_dir,
                issue_location=config.issue_location,
                signatory_name=config.signatory_name,
                signatory_title=config.signatory_title,
            )
        )
        # When not injected, resolve the configured backend lazily at run time
        # (so STORAGE_PROVIDER is honoured and tests can inject a fake).
        self._storage = storage

    def generate_from_excel(
        self,
        excel_source: Path | str | IO[bytes],
        form_data: CertificateFormData,
        visual_template_layout: dict | None = None,
    ) -> list[GeneratedCertificateResult]:
        participants = read_participants(excel_source)
        participants = self._merge_form_data(participants, form_data)
        records = enrich_with_registry(participants)

        codes = allocate_codes(len(records))
        records = [
            ParticipantRegistryRecord(
                nome=r.nome,
                email=r.email,
                curso=r.curso,
                livro=r.livro,
                folha=r.folha,
                linha=r.linha,
                validation_code=code,
                referencia_registro=r.referencia_registro,
                texto_certificado=r.texto_certificado,
                certificate_text=r.certificate_text or r.texto_certificado,
                data_emissao=r.data_emissao,
            )
            for r, code in zip(records, codes)
        ]

        storage = self._storage or get_storage()
        max_bytes = storage_config.get_max_file_size_bytes()

        results: list[GeneratedCertificateResult] = []
        db_entries: list[dict] = []

        for record in records:
            # 1) render the PDF in memory (no PDF is ever left on disk for the
            #    Drive backend; the local backend writes it under storage/pdfs).
            content = self._render_pdf_bytes(record, visual_template_layout)
            if max_bytes is not None and len(content) > max_bytes:
                raise ValueError(
                    f"Certificado de '{record.nome}' excede o tamanho máximo permitido."
                )

            # 2) persist the bytes through the configured storage backend.
            stored = storage.save(
                content,
                filename=build_pdf_filename(record),
                mime_type="application/pdf",
            )

            # 3) public file URL is code-based and proxied by the backend —
            #    it never exposes a provider path/link.
            results.append(
                GeneratedCertificateResult(
                    name=record.nome,
                    file_url=f"/certificate-file/{record.validation_code}",
                    livro=record.livro,
                    folha=record.folha,
                    linha=record.linha,
                    validation_code=record.validation_code,
                    pdf_path=stored.pdf_path,
                )
            )
            db_entries.append(
                {
                    "validationCode": record.validation_code,
                    "name": record.nome,
                    "event": record.curso,
                    "issued_at": record.data_emissao,
                    "date": record.data_emissao,
                    "certificate_text": _build_full_certificate_text(record),
                    **stored.as_db_fields(),
                }
            )

        # 4) persist metadata only after every upload succeeded.
        save_certificates(db_entries)
        return results

    def _render_pdf_bytes(
        self,
        record: ParticipantRegistryRecord,
        visual_template_layout: dict | None,
    ) -> bytes:
        if visual_template_layout:
            return self.generator.render_pdf_bytes_visual(record, visual_template_layout)
        template_path = get_template_for_course(record.curso, self.config.template_path)
        return self.generator.render_pdf_bytes_default(record, template_path=template_path)

    # ── Structured generation (new model: idempotent + QR) ──────────────────────

    def generate_certificates(
        self,
        rows: list[SpreadsheetRow],
        *,
        issued_by: int | None = None,
        visual_template_layout: dict | None = None,
    ) -> GenerationSummary:
        """Generate certificates for already-validated rows.

        Idempotent: rows whose business_key already exists are skipped and
        reported as duplicates (no new PDF/code). Each new certificate gets a
        unique code, a QR code pointing at the public validation URL, is stored
        through the configured backend and persisted with full metadata.
        """
        storage = self._storage or get_storage()
        max_bytes = storage_config.get_max_file_size_bytes()
        base_url = storage_config.get_public_validation_base_url()

        new_items: list[tuple[SpreadsheetRow, str]] = []
        duplicates: list[dict] = []
        for row in rows:
            key = compute_business_key(row)
            existing = db.get_by_business_key(key)
            if existing:
                duplicates.append(
                    {"name": row.nome, "existing_code": existing["unique_code"]}
                )
            else:
                new_items.append((row, key))

        codes = allocate_codes(len(new_items)) if new_items else []

        generated: list[dict] = []
        db_entries: list[dict] = []
        for (row, business_key), code in zip(new_items, codes):
            record = _row_to_record(row, code)
            qr_url = f"{base_url}/validar/{code}" if base_url else code

            if visual_template_layout:
                content = self.generator.render_pdf_bytes_visual(
                    record, visual_template_layout, qr_url=qr_url
                )
            else:
                template_path = get_template_for_course(row.curso, self.config.template_path)
                content = self.generator.render_pdf_bytes_default(
                    record, template_path=template_path, qr_url=qr_url
                )

            if max_bytes is not None and len(content) > max_bytes:
                raise ValueError(
                    f"Certificado de '{row.nome}' excede o tamanho máximo permitido."
                )

            stored = storage.save(
                content, filename=build_pdf_filename(record), mime_type="application/pdf"
            )
            generated.append({"name": row.nome, "code": code})
            db_entries.append(
                {
                    "validationCode": code,
                    "name": row.nome,
                    "participant_email": row.email or None,
                    "participant_document": row.documento or None,
                    "course_name": row.curso,
                    "event": row.evento,  # event_name = evento (NUNCA o curso)
                    "workload_hours": row.carga_horaria,
                    "issued_at": row.data_emissao,
                    "date": row.data_emissao,
                    "start_date": row.data_inicio or None,
                    "end_date": row.data_fim or None,
                    "certificate_text": _build_full_certificate_text(record),
                    "business_key": business_key,
                    "issued_by": issued_by,
                    **stored.as_db_fields(),
                }
            )

        save_certificates(db_entries)
        return GenerationSummary(
            generated=generated, duplicates=duplicates, total_valid=len(rows)
        )

    def reissue_certificate(self, cert: dict) -> None:
        """Re-render and re-upload the PDF for an existing certificate (same code).

        Controlled operation: only available for certificates that carry the
        structured fields (course/event/workload). Keeps the verification code.
        """
        if not (cert.get("event_name") and cert.get("workload_hours") and cert.get("course_name")):
            raise ValueError(
                "Reemissão indisponível para certificados antigos sem dados estruturados."
            )
        storage = self._storage or get_storage()
        base_url = storage_config.get_public_validation_base_url()
        code = cert["unique_code"]

        row = SpreadsheetRow(
            row_number=0,
            nome=cert["participant_name"],
            curso=cert["course_name"],
            evento=cert["event_name"],
            carga_horaria=int(cert["workload_hours"]),
            data_emissao=cert.get("issue_date") or "",
            email=cert.get("participant_email") or "",
            documento=cert.get("participant_document") or "",
            data_inicio=cert.get("start_date") or "",
            data_fim=cert.get("end_date") or "",
        )
        record = _row_to_record(row, code)
        qr_url = f"{base_url}/validar/{code}" if base_url else code
        template_path = get_template_for_course(row.curso, self.config.template_path)
        content = self.generator.render_pdf_bytes_default(
            record, template_path=template_path, qr_url=qr_url
        )
        stored = storage.save(
            content, filename=build_pdf_filename(record), mime_type="application/pdf"
        )
        db.update_certificate_file(code, stored.as_db_fields())

    def _merge_form_data(
        self,
        participants: list[Participant],
        form_data: CertificateFormData,
    ) -> list[Participant]:
        normalized_form_data = _normalize_form_data(form_data)
        return [
            Participant(
                nome=participant.nome,
                email=participant.email,
                curso=participant.curso,
                texto_certificado=normalized_form_data.texto_certificado,
                certificate_text=normalized_form_data.texto_certificado,
                data_emissao=normalized_form_data.data_emissao,
            )
            for participant in participants
        ]


def _normalize_form_data(form_data: CertificateFormData) -> CertificateFormData:
    # Normalise line endings from textarea (\r\n -> \n) and strip surrounding whitespace
    texto_certificado = form_data.texto_certificado.replace("\r\n", "\n").replace("\r", "\n").strip()
    data_emissao = _normalize_date_text(form_data.data_emissao.strip())

    missing_fields: list[str] = []
    if not texto_certificado:
        missing_fields.append("texto_certificado")
    if not data_emissao:
        missing_fields.append("data_emissao")

    if missing_fields:
        raise ValueError(
            "Campos obrigatorios ausentes no formulario: " + ", ".join(missing_fields)
        )

    return CertificateFormData(
        texto_certificado=texto_certificado,
        data_emissao=data_emissao,
    )


def _build_body(row: SpreadsheetRow) -> str:
    """Compose the certificate body text from the structured row."""
    parts = [
        f"participou do(a) {row.evento}",
        f"do curso de {row.curso}",
        f"com carga horária de {row.carga_horaria} horas",
    ]
    body = ", ".join(parts)
    if row.data_inicio and row.data_fim:
        body += f", realizado de {row.data_inicio} a {row.data_fim}"
    elif row.data_fim:
        body += f", realizado em {row.data_fim}"
    return body + "."


def _row_to_record(row: SpreadsheetRow, code: str) -> ParticipantRegistryRecord:
    body = _build_body(row)
    return ParticipantRegistryRecord(
        nome=row.nome,
        email=row.email,
        curso=row.curso,
        livro=0,
        folha=0,
        linha=0,
        validation_code=code,
        texto_certificado=body,
        certificate_text=body,
        data_emissao=row.data_emissao,
    )


def _build_full_certificate_text(record: ParticipantRegistryRecord) -> str:
    body = (record.certificate_text or record.texto_certificado).strip()
    if body and body[-1] not in ".!?":
        body = f"{body}."

    prefix = f"Certificamos que {record.nome}"
    date_text = f"Emitido em {record.data_emissao}." if record.data_emissao else ""
    return " ".join(part for part in (prefix, body, date_text) if part).strip()


# Backwards-compatible alias: date normalisation now lives in utils.dates
# (single source of truth, accented month names).
_normalize_date_text = normalize_date_text
