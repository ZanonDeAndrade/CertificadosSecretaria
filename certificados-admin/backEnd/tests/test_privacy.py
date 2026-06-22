from __future__ import annotations

import pytest

from database import config
from database.privacy import (
    document_hash,
    normalize_document,
    normalize_name,
    validate_production_privacy_config,
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
    monkeypatch.setenv(
        "DOCUMENT_HASH_SECRET", "T8v!mZ2#qL9@pR4$xN7&cB1*eK6-wY3+"
    )
    monkeypatch.setenv("MINIMIZE_DOCUMENT_PLAINTEXT", "true")
    validate_production_privacy_config()


def test_production_requires_plaintext_minimization(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv(
        "DOCUMENT_HASH_SECRET", "T8v!mZ2#qL9@pR4$xN7&cB1*eK6-wY3+"
    )
    monkeypatch.setenv("MINIMIZE_DOCUMENT_PLAINTEXT", "false")
    with pytest.raises(config.ConfigError, match="MINIMIZE_DOCUMENT_PLAINTEXT"):
        validate_production_privacy_config()
