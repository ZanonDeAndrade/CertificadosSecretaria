from __future__ import annotations

import sys
from pathlib import Path as _Path

# When this file is executed directly (python backEnd/services/certificate_service.py),
# Python puts backEnd/services/ on sys.path, which is one level too deep for
# bare imports like "from models import ...".  We always want backEnd/ on the path.
_BACKEND_DIR = str(_Path(__file__).resolve().parent.parent)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from models import ParticipantRegistryRecord
from services import certificate_store  # generate_code (monkeypatchable in tests)
from services import template_service
from services.generator import (
    CertificateGenerator,
    CertificateGeneratorConfig,
    build_pdf_filename,
)
from services.spreadsheet import SpreadsheetRow, compute_business_key
from services.certificate_text import render_certificate_body
from utils.dates import extenso_from_iso, normalize_date_text, to_iso

# certificate_store (imported above) puts the repo root on sys.path, so the
# shared storage layer / database resolve here regardless of the working dir.
from storage_service import CertificateStorage, StorageError, get_storage
from storage_service import config as storage_config
from database import db
import observability

LOGGER = logging.getLogger("certificados.saga")


def _metric(name: str) -> None:
    observability.metrics.increment(name)


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
class GenerationSummary:
    """Outcome of a confirmed batch generation (saga model).

    The lists reflect EXACTLY what was persisted:
      - ``generated``  → reserved, uploaded and finalized (status ``ativo``).
      - ``duplicates`` → an existing certificate matched the business_key.
      - ``failed``     → reserved but compensated (status ``failed``, no file).
    """

    generated: list[dict]    # [{"name", "code"}]
    duplicates: list[dict]   # [{"name", "existing_code", "status"}]
    failed: list[dict]       # [{"name", "error"}]
    total_valid: int


@dataclass(slots=True, frozen=True)
class _EmitOutcome:
    status: str  # "generated" | "duplicate" | "failed"
    code: str | None = None
    existing: dict | None = None
    error: str | None = None
    pdf_path: str = ""


@dataclass(slots=True, frozen=True)
class _ActiveTemplate:
    """Resolved active global template, ready to render a batch."""

    version_id: int
    label: str
    layout: dict
    snapshot_json: str
    background: bytes


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

    def _active_template(self, created_by: int | None) -> _ActiveTemplate:
        """Resolve the single global active template version (seed default once)."""
        template_service.ensure_default_version(self.config.template_path, created_by=created_by)
        version = template_service.get_active_version()
        if not version:
            raise ValueError(
                "Nenhum template global ativo. Configure e ative um template antes de emitir."
            )
        background, _mime = template_service.get_background_bytes(version["id"])
        layout = version["layout"]
        return _ActiveTemplate(
            version_id=version["id"],
            label=f"v{version['version_number']}",
            layout=layout,
            snapshot_json=json.dumps(layout, ensure_ascii=False),
            background=background,
        )

    # ── Structured generation (saga: idempotent + QR + global template) ─────────

    def generate_certificates(
        self,
        rows: list[SpreadsheetRow],
        *,
        issued_by: int | None = None,
        body_template: str | None = None,
    ) -> GenerationSummary:
        """Generate certificates for already-validated rows using the single
        active global template version.

        ``body_template`` is the secretaria-authored body text (already validated
        by :func:`services.certificate_text.validate_body_template`). It is
        interpolated PER ROW and becomes the certificate ``certificate_text`` and
        the rendered body. When provided, the active template MUST expose a
        ``texto_certificado``/``certificate_text`` element to render it (otherwise
        generation is blocked) and the resolved body is folded into the
        idempotency key. When omitted (direct/legacy callers), the body falls
        back to the auto-composed text and the historical key is kept.

        Idempotent: rows whose business_key already exists are reported as
        duplicates. Each new certificate records ``template_version_id`` and an
        immutable ``template_snapshot`` so a reissue reproduces it faithfully.
        """
        storage = self._storage or get_storage()
        max_bytes = storage_config.get_max_file_size_bytes()
        year = datetime.now().year
        tmpl = self._active_template(created_by=issued_by)

        if body_template is not None and not _layout_has_body_element(tmpl.layout):
            raise ValueError(
                "O template ativo não possui um elemento de texto do corpo "
                "(texto_certificado ou certificate_text). Adicione esse elemento "
                "ao template no editor antes de emitir."
            )

        generated: list[dict] = []
        duplicates: list[dict] = []
        failed: list[dict] = []

        for row in rows:
            if body_template is not None:
                resolved_body = render_certificate_body(body_template, build_row_variables(row))
                key_body: str | None = resolved_body
            else:
                resolved_body = _build_body(row)
                key_body = None
            business_key = compute_business_key(row, key_body)
            fields = {
                "participant_name": row.nome,
                "participant_email": row.email or None,
                "participant_document": row.documento or None,
                "course_name": row.curso,
                "event_name": row.evento,  # event_name = evento (NUNCA o curso)
                "workload_hours": row.carga_horaria,
                # Stored as ISO (YYYY-MM-DD) for real-date ordering/indexing.
                "issue_date": to_iso(row.data_emissao) or row.data_emissao,
                "start_date": to_iso(row.data_inicio),
                "end_date": to_iso(row.data_fim),
                # Persist EXACTLY the rendered body (never the {{...}} template),
                # so the reissue reproduces it faithfully.
                "certificate_text": resolved_body,
                "issued_by": issued_by,
                "template_used": tmpl.label,
                "template_version_id": tmpl.version_id,
                "template_snapshot": tmpl.snapshot_json,
            }

            def _build(code: str, _row: SpreadsheetRow = row, _body: str = resolved_body):
                return _row_to_record(_row, code, body=_body)

            def _render(record: ParticipantRegistryRecord, code: str):
                qr_url = storage_config.build_public_validation_url(code)
                return self.generator.render_pdf_bytes_visual(
                    record, tmpl.layout, qr_url=qr_url, background_bytes=tmpl.background
                )

            outcome = self._emit_one(
                storage=storage,
                business_key=business_key,
                fields=fields,
                build_record=_build,
                render=_render,
                max_bytes=max_bytes,
                year=year,
                issued_by=issued_by,
            )
            if outcome.status == "generated":
                generated.append({"name": row.nome, "code": outcome.code})
                _metric(observability.CERTS_GENERATED)
            elif outcome.status == "duplicate":
                duplicates.append(
                    {
                        "name": row.nome,
                        "existing_code": outcome.existing["unique_code"],
                        "status": outcome.existing.get("status") or "ativo",
                    }
                )
                _metric(observability.CERTS_DUPLICATE)
            else:  # failed
                failed.append({"name": row.nome, "error": outcome.error})
                _metric(observability.CERTS_FAILED)

        return GenerationSummary(
            generated=generated,
            duplicates=duplicates,
            failed=failed,
            total_valid=len(rows),
        )

    # ── Saga core ────────────────────────────────────────────────────────────

    def _emit_one(
        self,
        *,
        storage: CertificateStorage,
        business_key: str | None,
        fields: dict,
        build_record: Callable[[str], ParticipantRegistryRecord],
        render: Callable[[ParticipantRegistryRecord, str], bytes],
        max_bytes: int | None,
        year: int,
        issued_by: int | None,
    ) -> _EmitOutcome:
        """Run one certificate through the saga.

        1. reserve (DB transaction, status ``pending``) — UNIQUE constraints only;
        2. render in memory + upload to storage (no definitive local copy);
        3. finalize (DB transaction, status ``ativo`` + drive metadata);
        4. on any failure: compensate (delete the uploaded file), mark ``failed``,
           audit — and never report success.
        """
        code, existing = db.reserve_certificate(
            business_key=business_key,
            fields=fields,
            code_factory=lambda: certificate_store.generate_code(year),
        )
        if existing is not None:
            return _EmitOutcome("duplicate", existing=existing)

        stored = None
        try:
            record = build_record(code)
            content = render(record, code)
            if max_bytes is not None and len(content) > max_bytes:
                raise ValueError(
                    f"Certificado de '{fields.get('participant_name')}' "
                    "excede o tamanho máximo permitido."
                )
            stored = storage.save(
                content, filename=build_pdf_filename(record), mime_type="application/pdf"
            )
            if not db.finalize_certificate(code, stored.as_db_fields()):
                raise RuntimeError(
                    f"Finalização não afetou nenhuma linha para {code} "
                    "(reserva ausente ou já finalizada)."
                )
            return _EmitOutcome("generated", code=code, pdf_path=stored.pdf_path)
        except Exception as exc:  # noqa: BLE001 — saga must compensate any failure
            self._compensate(storage, code, stored, reason=str(exc), actor=issued_by)
            return _EmitOutcome("failed", code=code, error=_failure_message(exc))

    def _compensate(
        self,
        storage: CertificateStorage,
        code: str,
        stored,
        *,
        reason: str,
        actor: int | None,
    ) -> None:
        """Compensate a failed emission: delete any uploaded file, mark failed, audit."""
        _metric(observability.CERTS_COMPENSATED)
        drive_file_id = stored.drive_file_id if stored else None
        drive_folder_id = stored.drive_folder_id if stored else None
        pdf_path = stored.pdf_path if stored else None

        # 1) Durably record the failure + any orphan pointer FIRST, so even if the
        #    delete below fails (or we crash), reconciliation can clean it up.
        db.mark_certificate_failed(
            code,
            drive_file_id=drive_file_id,
            drive_folder_id=drive_folder_id,
            pdf_path=pdf_path,
        )

        # 2) If an upload happened, delete the file and clear the pointer.
        if stored is not None and ((drive_file_id or "") or (pdf_path or "")):
            locator = {
                "drive_file_id": drive_file_id,
                "drive_folder_id": drive_folder_id,
                "pdf_path": pdf_path,
                "storage_provider": stored.storage_provider,
            }
            try:
                storage.delete(locator)
                db.clear_certificate_storage(code)
            except (StorageError, FileNotFoundError, OSError) as del_exc:
                LOGGER.error(
                    "Compensação: falha ao excluir arquivo de %s (%s); "
                    "será tratado pela reconciliação.",
                    code,
                    del_exc,
                )

        # 3) Audit the failure.
        db.insert_audit_log(
            action="generation_failed",
            actor_id=actor,
            target_type="certificate",
            target_id=code,
            details=(reason or "")[:480],
        )

    def reissue_certificate(self, cert: dict) -> None:
        """Re-render a certificate FAITHFULLY using its original template version.

        Uses the certificate's stored ``template_version_id`` + immutable
        ``template_snapshot`` (same code, same version). The Drive swap is
        crash-safe: the NEW file is finalized in the DB BEFORE the old one is
        deleted, and if the DB update fails the new file is removed and the
        previous file is preserved (no orphans, no data loss).
        """
        if not cert.get("template_version_id") or not cert.get("template_snapshot"):
            raise ValueError(
                "Reemissão indisponível: certificado sem versão/snapshot de template."
            )
        storage = self._storage or get_storage()
        code = cert["unique_code"]
        version_id = int(cert["template_version_id"])
        try:
            snapshot = json.loads(cert["template_snapshot"])
        except (TypeError, ValueError) as exc:
            raise ValueError("Snapshot de template inválido.") from exc
        background, _mime = template_service.get_background_bytes(version_id)

        record = _cert_to_record(cert, code)
        qr_url = storage_config.build_public_validation_url(code)
        content = self.generator.render_pdf_bytes_visual(
            record, snapshot, qr_url=qr_url, background_bytes=background
        )

        old_locator = {
            "storage_provider": cert.get("storage_provider"),
            "drive_file_id": cert.get("drive_file_id"),
            "drive_folder_id": cert.get("drive_folder_id"),
            "pdf_path": cert.get("pdf_path"),
        }
        old_has_file = bool((cert.get("drive_file_id") or "") or (cert.get("pdf_path") or ""))

        # 1) Upload the NEW file.
        stored = storage.save(
            content, filename=build_pdf_filename(record), mime_type="application/pdf"
        )

        # 2) Finalize the NEW file in the DB BEFORE deleting the old one.
        try:
            if not db.update_certificate_file(code, stored.as_db_fields()):
                raise RuntimeError("Atualização do certificado não afetou nenhuma linha.")
        except Exception:
            # Rollback: delete the just-uploaded NEW file and PRESERVE the old one
            # (the DB still points at it).
            self._safe_delete(storage, {
                "storage_provider": stored.storage_provider,
                "drive_file_id": stored.drive_file_id,
                "drive_folder_id": stored.drive_folder_id,
                "pdf_path": stored.pdf_path,
            })
            db.insert_audit_log(
                action="reissue_failed",
                target_type="certificate",
                target_id=code,
                details="rollback: arquivo anterior preservado",
            )
            raise

        # 3) Delete the OLD file — only now that the new one is finalized. Skip if
        #    it is the same underlying file (local overwrite of a fixed path).
        if old_has_file and not _same_storage_target(old_locator, stored):
            if not self._safe_delete(storage, old_locator):
                LOGGER.error(
                    "Reemissão %s: arquivo anterior não pôde ser removido "
                    "(será tratado pela reconciliação).",
                    code,
                )

    def _safe_delete(self, storage: CertificateStorage, locator: dict) -> bool:
        try:
            storage.delete(locator)
            return True
        except (StorageError, FileNotFoundError, OSError) as exc:
            LOGGER.error("Falha ao excluir arquivo no storage: %s", exc)
            return False

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


# Template element keys that render the secretaria-authored certificate body.
_BODY_ELEMENT_KEYS = {"texto_certificado", "certificate_text"}


def _layout_has_body_element(layout: dict) -> bool:
    """True if the layout has a text element that renders the certificate body."""
    for element in layout.get("elements", []) or []:
        if (
            isinstance(element, dict)
            and element.get("type", "text") == "text"
            and element.get("key") in _BODY_ELEMENT_KEYS
        ):
            return True
    return False


def build_row_variables(row: SpreadsheetRow) -> dict[str, str]:
    """Map a validated row to the variables allowed in the body template.

    ``carga_horaria`` is the number ONLY ("horas" is written by the secretaria);
    dates pass through as already normalised (por extenso) strings.
    """
    return {
        "nome": row.nome,
        "curso": row.curso,
        "evento": row.evento,
        "carga_horaria": str(row.carga_horaria),
        "data_inicio": row.data_inicio or "",
        "data_fim": row.data_fim or "",
        "data_emissao": row.data_emissao or "",
    }


def _row_to_record(
    row: SpreadsheetRow, code: str, body: str | None = None
) -> ParticipantRegistryRecord:
    resolved = body if body is not None else _build_body(row)
    return ParticipantRegistryRecord(
        nome=row.nome,
        email=row.email,
        curso=row.curso,
        evento=row.evento,  # event and course are distinct (bug fix)
        livro=0,
        folha=0,
        linha=0,
        validation_code=code,
        texto_certificado=resolved,
        certificate_text=resolved,
        data_emissao=row.data_emissao,
    )


def _cert_to_record(cert: dict, code: str) -> ParticipantRegistryRecord:
    """Build a render record from a persisted certificate row (for reissue)."""
    body = (cert.get("certificate_text") or "").strip()
    return ParticipantRegistryRecord(
        nome=cert.get("participant_name") or "",
        email=cert.get("participant_email") or "",
        curso=cert.get("course_name") or "",
        evento=cert.get("event_name") or "",
        livro=0,
        folha=0,
        linha=0,
        validation_code=code,
        texto_certificado=body,
        certificate_text=body,
        # Stored ISO → render 'por extenso' on the reissued PDF.
        data_emissao=extenso_from_iso(cert.get("issue_date")),
    )


def _same_storage_target(old_locator: dict, stored) -> bool:
    """True if the old and new uploads point at the SAME underlying file.

    On local storage the filename is deterministic, so a reissue overwrites the
    same path — deleting "the old one" would delete the new file. On Drive each
    upload is a new file id, so they always differ.
    """
    old_drive = (old_locator.get("drive_file_id") or "").strip()
    new_drive = (getattr(stored, "drive_file_id", None) or "").strip()
    if old_drive or new_drive:
        return bool(old_drive) and old_drive == new_drive
    old_path = (old_locator.get("pdf_path") or "").strip()
    new_path = (getattr(stored, "pdf_path", None) or "").strip()
    return bool(old_path) and old_path == new_path


def _failure_message(exc: Exception) -> str:
    """User-facing message for a failed emission (never leaks internals)."""
    if isinstance(exc, ValueError):
        return str(exc)
    if isinstance(exc, StorageError):
        return "Falha ao enviar o certificado para o armazenamento."
    return "Falha inesperada ao gerar o certificado."


# Backwards-compatible alias: date normalisation now lives in utils.dates
# (single source of truth, accented month names).
_normalize_date_text = normalize_date_text
