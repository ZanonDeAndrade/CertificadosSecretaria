"""Privacy-preserving normalization and pseudonymization helpers."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import unicodedata

from . import config

_DEV_SECRET = "development-only-document-secret-change-in-production"


def normalize_name(value: str | None) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "")
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(without_marks.casefold().split())


def normalize_document(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    return "".join(ch for ch in normalized if ch.isalnum())


def _secret() -> bytes:
    raw = config.read_secret("DOCUMENT_HASH_SECRET")
    if not raw:
        if config.is_production():
            raise config.ConfigError("APP_ENV=production exige DOCUMENT_HASH_SECRET forte.")
        raw = _DEV_SECRET
    return raw.encode("utf-8")


def validate_production_privacy_config() -> None:
    if not config.is_production():
        return
    raw = config.read_secret("DOCUMENT_HASH_SECRET")
    if len(raw.encode("utf-8")) < 32 or len(set(raw)) < 12 or re.fullmatch(r"(.)\1+", raw):
        raise config.ConfigError(
            "DOCUMENT_HASH_SECRET deve ter ao menos 32 bytes e alta entropia em produção."
        )
    if os.getenv("MINIMIZE_DOCUMENT_PLAINTEXT", "true").strip().lower() in {
        "0",
        "false",
        "no",
    }:
        raise config.ConfigError(
            "MINIMIZE_DOCUMENT_PLAINTEXT deve permanecer true em produção."
        )


def document_hash(value: str | None) -> str | None:
    normalized = normalize_document(value)
    if not normalized:
        return None
    return hmac.new(_secret(), f"document:v1:{normalized}".encode(), hashlib.sha256).hexdigest()


def certificate_challenge(unique_code: str) -> str:
    digest = hmac.new(
        _secret(), f"certificate-ref:v1:{unique_code}".encode(), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def hash_matches_document(expected_hash: str | None, document: str | None) -> bool:
    candidate = document_hash(document)
    return bool(expected_hash and candidate and hmac.compare_digest(expected_hash, candidate))
