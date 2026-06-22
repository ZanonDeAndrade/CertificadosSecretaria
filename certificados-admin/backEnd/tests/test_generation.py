"""Tests for structured generation: idempotency, metadata, and QR code."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_DIR.parent.parent
for _p in (str(_BACKEND_DIR), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from services.certificate_service import CertificateBatchConfig, CertificateBatchService
from services.spreadsheet import SpreadsheetRow
from storage_service.local import LocalStorage

PDF_BYTES = b"%PDF-1.4\nfake\n%%EOF"


class FakeGenerator:
    def __init__(self):
        self.qr_urls: list[str] = []

    def render_pdf_bytes_default(self, record, template_path=None, qr_url=None):
        self.qr_urls.append(qr_url)
        return PDF_BYTES

    def render_pdf_bytes_visual(self, record, layout, *, qr_url=None, background_bytes=None):
        self.qr_urls.append(qr_url)
        return PDF_BYTES


def _service(tmp_path, generator=None):
    config = CertificateBatchConfig(
        template_path=tmp_path / "t.png",
        regular_font_path=tmp_path / "r.ttf",
        bold_font_path=tmp_path / "b.ttf",
        output_dir=tmp_path / "pdfs",
    )
    storage = LocalStorage(pdfs_dir=tmp_path / "pdfs", storage_dir=tmp_path)
    return CertificateBatchService(config, storage=storage, generator=generator or FakeGenerator())


def _point_db(monkeypatch, tmp_path):
    from database import db

    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "c.db")
    monkeypatch.setattr(db, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(db, "PDFS_DIR", tmp_path / "pdfs")
    db.init_db()
    return db


def _row(nome="Ana Souza", evento="Semana Jurídica"):
    return SpreadsheetRow(
        row_number=2,
        nome=nome,
        curso="Direito",
        evento=evento,
        carga_horaria=40,
        data_emissao="10 de junho de 2026",
        email="ana@x.com",
        documento="123",
    )


def test_generation_persists_structured_metadata(monkeypatch, tmp_path):
    db = _point_db(monkeypatch, tmp_path)
    service = _service(tmp_path)
    issuer_id = db.create_admin_user("secretaria", "hash")  # FK target for issued_by

    summary = service.generate_certificates([_row()], issued_by=issuer_id)
    assert len(summary.generated) == 1
    code = summary.generated[0]["code"]

    row = db.get_by_code(code)
    assert row["course_name"] == "Direito"
    assert row["event_name"] == "Semana Jurídica"  # evento, NOT the course
    assert row["workload_hours"] == 40
    assert row["participant_email"] == "ana@x.com"
    assert row["participant_document"] is None
    assert row["participant_document_hash"]
    assert row["participant_name_normalized"] == "ana souza"
    assert row["issued_by"] == issuer_id
    assert row["business_key"]
    assert row["storage_provider"] == "local"
    # F8: the issue date is stored ISO (chronologically sortable), not 'por extenso'.
    assert row["issue_date"] == "2026-06-10"


def test_generation_is_idempotent(monkeypatch, tmp_path):
    db = _point_db(monkeypatch, tmp_path)
    service = _service(tmp_path)

    first = service.generate_certificates([_row()])
    assert len(first.generated) == 1
    assert len(first.duplicates) == 0
    code = first.generated[0]["code"]

    # Re-submitting the same row generates nothing new and reports the duplicate.
    second = service.generate_certificates([_row()])
    assert len(second.generated) == 0
    assert len(second.duplicates) == 1
    assert second.duplicates[0]["existing_code"] == code

    # Only one row in the DB.
    _, total = db.list_certificates()
    assert total == 1


def test_qr_url_passed_to_generator(monkeypatch, tmp_path):
    _point_db(monkeypatch, tmp_path)
    monkeypatch.setenv("PUBLIC_VALIDATION_BASE_URL", "https://cert.example.edu")
    gen = FakeGenerator()
    service = _service(tmp_path, generator=gen)

    summary = service.generate_certificates([_row()])
    code = summary.generated[0]["code"]
    assert gen.qr_urls == [f"https://cert.example.edu/validar/{code}"]


@pytest.mark.parametrize(
    "invalid_url",
    [
        "cert.example.edu",
        "ftp://cert.example.edu",
        "https://user:secret@cert.example.edu",
        "https://cert.example.edu?tenant=1",
        "https://cert.example.edu/#fragment",
        "https://cert.example.edu\\invalid",
    ],
)
def test_public_validation_base_url_rejects_invalid_values(monkeypatch, invalid_url):
    from storage_service import StorageConfigError
    from storage_service import config as storage_config

    monkeypatch.setenv("PUBLIC_VALIDATION_BASE_URL", invalid_url)
    with pytest.raises(StorageConfigError):
        storage_config.get_public_validation_base_url()


def test_production_requires_explicit_https_validation_url(monkeypatch):
    from storage_service import StorageConfigError
    from storage_service import config as storage_config

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("PUBLIC_VALIDATION_BASE_URL", raising=False)
    with pytest.raises(StorageConfigError):
        storage_config.validate_production_public_validation_url()

    monkeypatch.setenv("PUBLIC_VALIDATION_BASE_URL", "http://cert.example.edu")
    with pytest.raises(StorageConfigError):
        storage_config.validate_production_public_validation_url()

    monkeypatch.setenv("PUBLIC_VALIDATION_BASE_URL", "https://cert.example.edu/")
    storage_config.validate_production_public_validation_url()


def test_make_qr_image_is_not_blank():
    from services.generator import make_qr_image

    img = make_qr_image("https://cert.example.edu/validar/CERT-2026-AB1234", 200)
    assert img.size == (200, 200)
    colors = {px[:3] for px in img.getdata()}
    # Must contain both dark and light modules.
    assert any(sum(c) < 200 for c in colors)  # dark present
    assert any(sum(c) > 600 for c in colors)  # light present


def test_real_generator_embeds_qr(tmp_path, monkeypatch):
    """Integration: the real generator produces a valid PDF with a QR url."""
    _point_db(monkeypatch, tmp_path)
    from services.generator import CertificateGenerator, CertificateGeneratorConfig

    be = _BACKEND_DIR
    gen = CertificateGenerator(
        CertificateGeneratorConfig(
            template_path=be / "templates" / "certificado_base.png",
            regular_font_path=be / "fonts" / "times.ttf",
            bold_font_path=be / "fonts" / "timesbd.ttf",
            output_dir=tmp_path / "pdfs",
        )
    )
    record = _row()
    from services.certificate_service import _row_to_record

    rec = _row_to_record(record, "CERT-2026-QR0001")
    with_qr = gen.render_pdf_bytes_default(
        rec, qr_url="https://cert.example.edu/validar/CERT-2026-QR0001"
    )
    without_qr = gen.render_pdf_bytes_default(rec, qr_url=None)
    assert with_qr[:4] == b"%PDF"
    # The QR adds visible content → the PDF is larger than without it.
    assert len(with_qr) > len(without_qr)


def _decode_clean_qr(image) -> str:
    """Decode a clean generated QR matrix independently from its input data.

    This intentionally reads pixels from the rendered certificate. The qrcode
    package is used only for QR layout tables (reserved cells / RS block sizes),
    not to recover or compare the original payload.
    """
    import qrcode
    from qrcode import base, util

    grayscale = image.convert("L")
    width, height = grayscale.size
    assert width == height
    border = 2

    sampled = None
    version = None

    def finder_matches(matrix, left, top):
        for row in range(7):
            for col in range(7):
                expected = (
                    row in {0, 6}
                    or col in {0, 6}
                    or (2 <= row <= 4 and 2 <= col <= 4)
                )
                if matrix[top + row][left + col] != expected:
                    return False
        return True

    for candidate_version in range(1, 11):
        count = 17 + 4 * candidate_version
        total = count + border * 2
        matrix = [
            [
                grayscale.getpixel(
                    (
                        min(width - 1, int((border + col + 0.5) * width / total)),
                        min(height - 1, int((border + row + 0.5) * height / total)),
                    )
                )
                < 128
                for col in range(count)
            ]
            for row in range(count)
        ]
        if (
            finder_matches(matrix, 0, 0)
            and finder_matches(matrix, count - 7, 0)
            and finder_matches(matrix, 0, count - 7)
        ):
            sampled = matrix
            version = candidate_version
            break

    assert sampled is not None and version is not None, "QR finder patterns not found"
    count = len(sampled)

    # Build the reserved-cell map exactly as a decoder does before reading data.
    layout = qrcode.QRCode(
        version=version,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        border=0,
    )
    layout.modules_count = count
    layout.modules = [[None] * count for _ in range(count)]
    layout.setup_position_probe_pattern(0, 0)
    layout.setup_position_probe_pattern(count - 7, 0)
    layout.setup_position_probe_pattern(0, count - 7)
    layout.setup_position_adjust_pattern()
    layout.setup_timing_pattern()
    layout.setup_type_info(True, 0)
    if version >= 7:
        layout.setup_type_number(True)

    rs_blocks = base.rs_blocks(version, qrcode.constants.ERROR_CORRECT_M)
    raw_count = sum(block.total_count for block in rs_blocks)

    for mask_pattern in range(8):
        mask = util.mask_func(mask_pattern)
        bits = []
        row = count - 1
        increment = -1
        for column in range(count - 1, 0, -2):
            if column <= 6:
                column -= 1
            while True:
                for current_column in (column, column - 1):
                    if layout.modules[row][current_column] is None:
                        dark = sampled[row][current_column]
                        if mask(row, current_column):
                            dark = not dark
                        bits.append(1 if dark else 0)
                row += increment
                if row < 0 or row >= count:
                    row -= increment
                    increment = -increment
                    break

        raw = [
            sum(bits[index + offset] << (7 - offset) for offset in range(8))
            for index in range(0, raw_count * 8, 8)
        ]

        data_blocks = [[0] * block.data_count for block in rs_blocks]
        cursor = 0
        for index in range(max(block.data_count for block in rs_blocks)):
            for block_index, block in enumerate(rs_blocks):
                if index < block.data_count:
                    data_blocks[block_index][index] = raw[cursor]
                    cursor += 1
        data = bytes(value for block in data_blocks for value in block)
        data_bits = "".join(f"{value:08b}" for value in data)
        if not data_bits.startswith("0100"):  # byte mode
            continue
        count_bits = 8 if version <= 9 else 16
        length = int(data_bits[4 : 4 + count_bits], 2)
        start = 4 + count_bits
        if start + length * 8 > len(data_bits):
            continue
        payload = bytes(
            int(data_bits[index : index + 8], 2)
            for index in range(start, start + length * 8, 8)
        )
        try:
            return payload.decode("utf-8")
        except UnicodeDecodeError:
            continue

    raise AssertionError("QR payload could not be decoded")


def test_real_certificate_qr_is_decodable(tmp_path, monkeypatch):
    """Contract: a real rendered certificate contains the canonical QR URL."""
    monkeypatch.setenv("PUBLIC_VALIDATION_BASE_URL", "https://cert.example.edu///")
    from services.certificate_service import _row_to_record
    from services.generator import (
        CertificateGenerator,
        CertificateGeneratorConfig,
        REGISTRY_BOTTOM_Y_RATIO,
        SIDE_MARGIN_RATIO,
    )
    from storage_service import config as storage_config

    generator = CertificateGenerator(
        CertificateGeneratorConfig(
            template_path=_BACKEND_DIR / "templates" / "certificado_base.png",
            regular_font_path=_BACKEND_DIR / "fonts" / "times.ttf",
            bold_font_path=_BACKEND_DIR / "fonts" / "timesbd.ttf",
            output_dir=tmp_path / "pdfs",
        )
    )
    code = "CERT-2026-QR0001"
    expected_url = storage_config.build_public_validation_url(code)
    rendered = generator._compose_default_image(
        _row_to_record(_row(), code), qr_url=expected_url
    )
    width, height = rendered.size
    qr_size = max(int(height * 0.12), 96)
    qr_x = int(width * SIDE_MARGIN_RATIO)
    qr_y = max(int(height * REGISTRY_BOTTOM_Y_RATIO) - qr_size, 0)
    qr_image = rendered.crop((qr_x, qr_y, qr_x + qr_size, qr_y + qr_size))

    assert _decode_clean_qr(qr_image) == expected_url
