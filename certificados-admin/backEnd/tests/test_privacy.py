from __future__ import annotations

import json

import pytest

from database import config
from database.privacy import (
    active_document_key_id,
    document_hash,
    email_hash,
    email_hash_candidates,
    is_valid_email,
    matching_document_key_id,
    matching_email_key_id,
    normalize_document,
    normalize_email,
    normalize_name,
    pseudonymous_rate_limit_key,
    validate_production_privacy_config,
)


def test_email_normalisation_validation_and_keyed_hash(monkeypatch):
    monkeypatch.setenv("DOCUMENT_HASH_SECRET", "s" * 32 + "abcdefghijkl")
    monkeypatch.setenv("DOCUMENT_HASH_ACTIVE_KEY_ID", "v1")
    assert normalize_email("  Ana.Silva @Exemplo.COM ") == "ana.silva@exemplo.com"
    assert is_valid_email("ana.silva@exemplo.com")
    assert is_valid_email(" Ana.Silva@Exemplo.com ")
    assert not is_valid_email("ana@exemplo")
    assert not is_valid_email("ana@@exemplo.com")
    assert not is_valid_email("ana exemplo.com")
    assert not is_valid_email("a" * 250 + "@exemplo.com")
    assert not is_valid_email("")

    digest = email_hash("Ana.Silva@Exemplo.com")
    assert digest == email_hash("ana.silva@exemplo.com")
    assert email_hash("") is None
    # Domain-separated from the document HMAC under the same key.
    assert digest != document_hash("ana.silva@exemplo.com")
    assert email_hash_candidates("ANA.silva@exemplo.com") == {"v1": digest}
    assert matching_email_key_id(digest, "ana.silva@exemplo.com", key_id="v1") == "v1"
    assert matching_email_key_id(digest, "ana.silva@exemplo.com") == "v1"
    assert matching_email_key_id(digest, "outra@exemplo.com", key_id="v1") is None
    assert matching_email_key_id(None, "ana.silva@exemplo.com") is None
    # The rate-limit pseudonym follows the same normalisation.
    assert pseudonymous_rate_limit_key("search-email", "Ana@Exemplo.com ") == (
        pseudonymous_rate_limit_key("search-email", "ana@exemplo.com")
    )
    assert pseudonymous_rate_limit_key("search-email", "ana@exemplo.com") != (
        pseudonymous_rate_limit_key("search-name", "ana@exemplo.com")
    )


def test_name_and_document_normalization(monkeypatch):
    monkeypatch.setenv("DOCUMENT_HASH_SECRET", "s" * 32 + "abcdefghijkl")
    assert normalize_name("  JOÃO   d'Ávila ") == "joao d'avila"
    assert normalize_document("999.999.999-99") == "99999999999"
    assert document_hash("999.999.999-99") == document_hash("99999999999")


@pytest.mark.parametrize("secret", ["", "short", "a" * 64])
def test_production_rejects_missing_or_weak_document_secret(monkeypatch, secret):
    monkeypatch.setenv("APP_ENV", "production")
    if secret:
        monkeypatch.setenv("DOCUMENT_HASH_SECRET", secret)
    else:
        monkeypatch.delenv("DOCUMENT_HASH_SECRET", raising=False)
    with pytest.raises(config.ConfigError):
        validate_production_privacy_config()


def test_production_accepts_strong_document_secret(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DOCUMENT_HASH_SECRET", "T8v!mZ2#qL9@pR4$xN7&cB1*eK6-wY3+")
    monkeypatch.setenv("MINIMIZE_DOCUMENT_PLAINTEXT", "true")
    validate_production_privacy_config()


def test_production_accepts_document_secret_file(monkeypatch, tmp_path):
    secret_file = tmp_path / "document_hash_secret"
    secret_file.write_text("T8v!mZ2#qL9@pR4$xN7&cB1*eK6-wY3+", encoding="utf-8")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("DOCUMENT_HASH_SECRET", raising=False)
    monkeypatch.setenv("DOCUMENT_HASH_SECRET_FILE", str(secret_file))
    monkeypatch.setenv("MINIMIZE_DOCUMENT_PLAINTEXT", "true")

    validate_production_privacy_config()


def test_production_requires_plaintext_minimization(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DOCUMENT_HASH_SECRET", "T8v!mZ2#qL9@pR4$xN7&cB1*eK6-wY3+")
    monkeypatch.setenv("MINIMIZE_DOCUMENT_PLAINTEXT", "false")
    with pytest.raises(config.ConfigError, match="MINIMIZE_DOCUMENT_PLAINTEXT"):
        validate_production_privacy_config()


def test_versioned_keyring_preserves_v1_and_writes_with_active_v2(monkeypatch, tmp_path):
    keyring = tmp_path / "document-keyring.json"
    keyring.write_text(
        json.dumps(
            {
                "v1": "Legacy-Key-For-Tests-1234567890!Aa",
                "v2": "Current-Key-For-Tests-0987654321!Bb",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DOCUMENT_HASH_KEYRING_FILE", str(keyring))
    monkeypatch.setenv("DOCUMENT_HASH_ACTIVE_KEY_ID", "v2")
    monkeypatch.delenv("DOCUMENT_HASH_SECRET", raising=False)
    monkeypatch.delenv("DOCUMENT_HASH_SECRET_FILE", raising=False)

    legacy_hash = document_hash("999.999.999-99", key_id="v1")
    current_hash = document_hash("999.999.999-99")
    assert active_document_key_id() == "v2"
    assert legacy_hash != current_hash
    assert matching_document_key_id(legacy_hash, "99999999999", key_id="v1") == "v1"
    assert matching_document_key_id(current_hash, "99999999999", key_id="v2") == "v2"


def test_keyring_fails_closed_when_active_version_is_missing(monkeypatch, tmp_path):
    keyring = tmp_path / "document-keyring.json"
    keyring.write_text(
        json.dumps({"v1": "Legacy-Key-For-Tests-1234567890!Aa"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("DOCUMENT_HASH_KEYRING_FILE", str(keyring))
    monkeypatch.setenv("DOCUMENT_HASH_ACTIVE_KEY_ID", "v2")
    monkeypatch.delenv("DOCUMENT_HASH_SECRET", raising=False)
    monkeypatch.delenv("DOCUMENT_HASH_SECRET_FILE", raising=False)

    with pytest.raises(config.ConfigError, match="ACTIVE_KEY_ID"):
        document_hash("99999999999")
