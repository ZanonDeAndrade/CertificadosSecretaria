"""Authenticated encryption for short-lived emission-job payloads.

The database stores ciphertext, nonce and a non-secret key identifier only.
Production keys are supplied as a JSON keyring through a mounted secret; this
allows rotation without making queued/retryable jobs unreadable.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from database import config as db_config

_DEV_KEY_ID = "development-v1"
_DEV_KEY = hashlib.sha256(b"certificados-secretaria-development-jobs-v1").digest()


class PayloadCryptoError(RuntimeError):
    """Payload key configuration or authentication failed."""


@dataclass(frozen=True, slots=True)
class EncryptedPayload:
    ciphertext: bytes
    nonce: bytes
    key_id: str


def _decode_key(value: str, key_id: str) -> bytes:
    try:
        padded = value.strip() + "=" * (-len(value.strip()) % 4)
        key = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (ValueError, UnicodeError) as exc:
        raise PayloadCryptoError(f"Chave de job inválida para o id {key_id!r}.") from exc
    if len(key) != 32:
        raise PayloadCryptoError(f"A chave de job {key_id!r} deve conter exatamente 32 bytes.")
    return key


def _keyring() -> tuple[str, dict[str, bytes]]:
    raw = db_config.read_secret("BATCH_PAYLOAD_KEYS")
    active = (os.getenv("BATCH_PAYLOAD_ACTIVE_KEY_ID") or "").strip()
    if not raw:
        if db_config.is_production() or db_config.is_local_server():
            raise PayloadCryptoError(
                "Este ambiente exige BATCH_PAYLOAD_KEYS_FILE e BATCH_PAYLOAD_ACTIVE_KEY_ID."
            )
        return _DEV_KEY_ID, {_DEV_KEY_ID: _DEV_KEY}
    try:
        values = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PayloadCryptoError("BATCH_PAYLOAD_KEYS deve ser um objeto JSON.") from exc
    if not isinstance(values, dict) or not values:
        raise PayloadCryptoError("BATCH_PAYLOAD_KEYS deve conter ao menos uma chave.")
    keys = {str(key_id): _decode_key(str(value), str(key_id)) for key_id, value in values.items()}
    if not active or active not in keys:
        raise PayloadCryptoError(
            "BATCH_PAYLOAD_ACTIVE_KEY_ID deve apontar para uma chave do keyring."
        )
    return active, keys


def validate_configuration() -> None:
    _keyring()


def encrypt_json(value: dict[str, Any], *, aad: str) -> EncryptedPayload:
    active, keys = _keyring()
    nonce = os.urandom(12)
    plaintext = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    ciphertext = AESGCM(keys[active]).encrypt(nonce, plaintext, aad.encode("utf-8"))
    return EncryptedPayload(ciphertext=ciphertext, nonce=nonce, key_id=active)


def decrypt_json(
    ciphertext: bytes,
    nonce: bytes,
    key_id: str,
    *,
    aad: str,
) -> dict[str, Any]:
    _active, keys = _keyring()
    key = keys.get(key_id)
    if key is None:
        raise PayloadCryptoError(f"Chave de job {key_id!r} não está disponível.")
    try:
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, aad.encode("utf-8"))
        value = json.loads(plaintext.decode("utf-8"))
    except (InvalidTag, UnicodeError, json.JSONDecodeError) as exc:
        raise PayloadCryptoError("Payload de job inválido ou adulterado.") from exc
    if not isinstance(value, dict):
        raise PayloadCryptoError("Payload de job possui formato inválido.")
    return value
