"""Privacy-preserving normalization and pseudonymization helpers.

Document identifiers are stored exclusively as keyed HMACs.  Keys are
versioned so an operator can add a new active key without making certificates
created with the previous key unverifiable.  Existing (pre-keyring) hashes are
explicitly identified as ``v1`` by migration 0006.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import unicodedata
from pathlib import Path

from . import config

_DEV_SECRET = "development-only-document-secret-change-in-production"
LEGACY_DOCUMENT_KEY_ID = "v1"
_KEY_ID_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,31}")


def normalize_name(value: str | None) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "")
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(without_marks.casefold().split())


def normalize_document(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    return "".join(ch for ch in normalized if ch.isalnum())


def active_document_key_id() -> str:
    key_id = (os.getenv("DOCUMENT_HASH_ACTIVE_KEY_ID") or LEGACY_DOCUMENT_KEY_ID).strip()
    if not _KEY_ID_RE.fullmatch(key_id):
        raise config.ConfigError("DOCUMENT_HASH_ACTIVE_KEY_ID deve ter 1 a 32 caracteres seguros.")
    return key_id


def _load_keyring_file() -> dict[str, str]:
    raw_path = (os.getenv("DOCUMENT_HASH_KEYRING_FILE") or "").strip()
    if not raw_path:
        return {}
    path = Path(raw_path).expanduser()
    if not path.is_file():
        raise config.ConfigError("DOCUMENT_HASH_KEYRING_FILE não encontrado.")
    try:
        parsed = json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise config.ConfigError(
            "DOCUMENT_HASH_KEYRING_FILE deve conter um objeto JSON válido."
        ) from exc
    if not isinstance(parsed, dict):
        raise config.ConfigError(
            "DOCUMENT_HASH_KEYRING_FILE deve conter um objeto JSON de chaves versionadas."
        )
    result: dict[str, str] = {}
    for raw_key_id, raw_secret in parsed.items():
        key_id = str(raw_key_id).strip()
        if not _KEY_ID_RE.fullmatch(key_id) or not isinstance(raw_secret, str):
            raise config.ConfigError(
                "DOCUMENT_HASH_KEYRING_FILE contém identificador ou valor inválido."
            )
        secret = raw_secret.strip()
        if not secret or "\n" in secret or "\r" in secret:
            raise config.ConfigError(
                "DOCUMENT_HASH_KEYRING_FILE contém uma chave vazia ou multilinha."
            )
        result[key_id] = secret
    return result


def document_keyring() -> dict[str, bytes]:
    """Load every document-HMAC key without logging or persisting its value.

    ``DOCUMENT_HASH_SECRET`` remains the compatibility source for key ``v1``.
    Rotations use a mounted JSON object in ``DOCUMENT_HASH_KEYRING_FILE`` and
    select the writer key with ``DOCUMENT_HASH_ACTIVE_KEY_ID``.
    """

    raw_keys = _load_keyring_file()
    legacy = config.read_secret("DOCUMENT_HASH_SECRET")
    if legacy:
        existing = raw_keys.get(LEGACY_DOCUMENT_KEY_ID)
        if existing and not hmac.compare_digest(existing, legacy):
            raise config.ConfigError("A chave v1 diverge entre DOCUMENT_HASH_SECRET e a keyring.")
        raw_keys.setdefault(LEGACY_DOCUMENT_KEY_ID, legacy)
    if not raw_keys and not config.is_production():
        raw_keys[LEGACY_DOCUMENT_KEY_ID] = _DEV_SECRET

    active = active_document_key_id()
    if active not in raw_keys:
        raise config.ConfigError("A keyring de documentos não contém DOCUMENT_HASH_ACTIVE_KEY_ID.")
    return {key_id: value.encode("utf-8") for key_id, value in raw_keys.items()}


def _secret(key_id: str | None = None) -> bytes:
    selected = key_id or active_document_key_id()
    try:
        return document_keyring()[selected]
    except KeyError as exc:
        raise config.ConfigError(
            "A versão de chave necessária para validar o documento não está disponível."
        ) from exc


def _strong_secret(raw: bytes) -> bool:
    return len(raw) >= 32 and len(set(raw)) >= 12 and not re.fullmatch(rb"(.)\1+", raw)


def validate_production_privacy_config() -> None:
    if not (config.is_production() or config.is_local_server()):
        return
    keys = document_keyring()
    if not keys or any(not _strong_secret(secret) for secret in keys.values()):
        raise config.ConfigError(
            "Cada chave de documento deve ter ao menos 32 bytes e alta entropia em produção."
        )
    fingerprints = {hashlib.sha256(secret).digest() for secret in keys.values()}
    if len(fingerprints) != len(keys):
        raise config.ConfigError("Versões distintas da keyring não podem reutilizar a mesma chave.")
    if os.getenv("MINIMIZE_DOCUMENT_PLAINTEXT", "true").strip().lower() in {
        "0",
        "false",
        "no",
    }:
        raise config.ConfigError("MINIMIZE_DOCUMENT_PLAINTEXT deve permanecer true em produção.")


def document_hash(value: str | None, *, key_id: str | None = None) -> str | None:
    normalized = normalize_document(value)
    if not normalized:
        return None
    return hmac.new(
        _secret(key_id), f"document:v1:{normalized}".encode(), hashlib.sha256
    ).hexdigest()


def document_hash_with_key_id(value: str | None) -> tuple[str | None, str | None]:
    key_id = active_document_key_id()
    digest = document_hash(value, key_id=key_id)
    return digest, key_id if digest else None


def document_hash_candidates(value: str | None) -> dict[str, str]:
    """Return the keyed hashes that may identify a stored academic record.

    Certificate rows keep the key version used when they were issued.  Public
    RA lookup therefore has to search every key that is still accepted during
    a rotation, without ever loading or storing the RA in plaintext.
    """

    normalized = normalize_document(value)
    if not normalized:
        return {}
    return {
        key_id: hmac.new(
            secret,
            f"document:v1:{normalized}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        for key_id, secret in document_keyring().items()
    }


def public_result_reference(unique_code: str) -> str:
    """Return a non-authorizing opaque selector for a name-search result.

    This value is domain-separated from the removed v1 download challenge and
    is accepted only together with a valid document/matriculation confirmation.
    """

    key_id = active_document_key_id()
    return hmac.new(
        _secret(key_id),
        f"public-result:v2:{key_id}:{unique_code}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def pseudonymous_rate_limit_key(scope: str, value: str | None) -> str:
    """HMAC an in-memory identity before it is stored as a rate-limit key."""

    normalized = normalize_document(value) if "document" in scope else normalize_name(value)
    if not normalized:
        normalized = "empty"
    key_id = active_document_key_id()
    return hmac.new(
        _secret(key_id),
        f"public-rate-limit:v1:{scope}:{normalized}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def matching_document_key_id(
    expected_hash: str | None,
    document: str | None,
    *,
    key_id: str | None = None,
) -> str | None:
    """Constant-time verification against the recorded key version.

    A missing version is treated as a legacy row and checked against every
    configured key without early return. Migration 0006 marks existing hashes
    as ``v1``; the fallback only protects databases during a rolling upgrade.
    """

    normalized = normalize_document(document)
    if not expected_hash or not normalized:
        return None
    keys = document_keyring()
    candidates = [key_id] if key_id else sorted(keys)
    matched: str | None = None
    for candidate_id in candidates:
        secret = keys.get(candidate_id)
        if secret is None:
            # Keep a digest comparison in the unavailable-key path too.
            candidate_hash = "0" * 64
        else:
            candidate_hash = hmac.new(
                secret,
                f"document:v1:{normalized}".encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
        if hmac.compare_digest(expected_hash, candidate_hash) and secret is not None:
            matched = candidate_id
    return matched


def hash_matches_document(
    expected_hash: str | None,
    document: str | None,
    *,
    key_id: str | None = None,
) -> bool:
    return matching_document_key_id(expected_hash, document, key_id=key_id) is not None
