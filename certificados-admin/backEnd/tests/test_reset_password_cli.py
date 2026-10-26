"""Password reset from the command line: same policy as "Alterar senha", every
session revoked, the change required at the next login and an audit entry
without any password material."""

from __future__ import annotations

import json
import logging

import pytest
from certificados_backend import auth, reset_password_cli
from sqlalchemy import select

from database import db
from database.models import AuditLog, AuthSession

ADMIN_USER = "secretaria"
ADMIN_PASS = "Senha-Sintetica-1!"
NEW_PASS = "Nova-Senha-Forte-2026!"


def _answers(*values: str):
    """A fake getpass that answers in order and records each prompt."""
    queue = list(values)
    prompts: list[str] = []

    def prompt(text: str) -> str:
        prompts.append(text)
        return queue.pop(0)

    prompt.prompts = prompts  # type: ignore[attr-defined]
    return prompt


def _cli_audits() -> list[AuditLog]:
    with db._session() as session:
        rows = session.execute(
            select(AuditLog).where(AuditLog.action == reset_password_cli.AUDIT_ACTION)
        ).scalars()
        return [row for row in rows]


def _user() -> dict:
    user = db.get_admin_user_by_username(ADMIN_USER)
    assert user is not None
    return user


def test_reset_applies_policy_revokes_sessions_and_audits(client, auth_headers, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    assert client.get("/auth/me").status_code == 200  # an open session to be revoked

    prompt = _answers(NEW_PASS, NEW_PASS)
    assert reset_password_cli.main([ADMIN_USER], prompt=prompt) == 0
    assert prompt.prompts == ["Nova senha: ", "Repita a nova senha: "]

    user = _user()
    assert auth.verify_password(NEW_PASS, user["password_hash"])
    assert not auth.verify_password(ADMIN_PASS, user["password_hash"])
    assert user["must_change_password"] == 1

    # The open session no longer works, and none is left unrevoked.
    assert client.get("/auth/me").status_code == 401
    with db._session() as session:
        sessions = session.execute(
            select(AuthSession).where(AuthSession.user_id == user["id"])
        ).scalars()
        reasons = {row.revoke_reason for row in sessions}
    assert reasons == {reset_password_cli.SESSION_REVOKE_REASON}

    [entry] = _cli_audits()
    assert entry.actor_id is None and entry.actor_username is None
    assert entry.target_type == "admin_user" and entry.target_id == str(user["id"])
    assert json.loads(entry.details or "{}") == {"scope": "cli", "session_count": 1}

    # The password never reaches the terminal, the logs or the audit trail.
    output = capsys.readouterr()
    for text in (output.out, output.err, caplog.text, entry.details or ""):
        assert NEW_PASS not in text
    assert "Sessões revogadas: 1" in output.out


def test_new_password_must_be_changed_at_the_next_login(client, auth_headers):
    assert reset_password_cli.main([ADMIN_USER], prompt=_answers(NEW_PASS, NEW_PASS)) == 0

    login = client.post("/auth/login", json={"username": ADMIN_USER, "password": NEW_PASS})
    assert login.status_code == 200, login.text
    assert client.get("/auth/me").json()["must_change_password"] is True
    blocked = client.get("/admin/users")
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "password_change_required"


def test_weak_password_is_refused_and_nothing_changes(client, capsys):
    before = _user()["password_hash"]
    prompt = _answers("curta", "curta", "semnumero", "semnumero", "abc", "abc")
    assert reset_password_cli.main([ADMIN_USER], prompt=prompt) == 1

    assert _user()["password_hash"] == before
    assert _user()["must_change_password"] == 0
    assert _cli_audits() == []
    output = capsys.readouterr()
    assert output.out.count("Senha recusada:") == 3
    assert "Nenhuma alteração foi feita." in output.err


def test_password_with_the_username_is_refused(client, capsys):
    prompt = _answers(*(["Secretaria-2026!x"] * 6))
    assert reset_password_cli.main([ADMIN_USER], prompt=prompt) == 1
    assert "nome de usuário" in capsys.readouterr().out
    assert _cli_audits() == []


def test_current_password_is_refused_like_in_change_password(client, capsys):
    prompt = _answers(*([ADMIN_PASS] * 6))
    assert reset_password_cli.main([ADMIN_USER], prompt=prompt) == 1
    assert "diferente da senha atual" in capsys.readouterr().out
    assert _cli_audits() == []


def test_mismatched_confirmation_asks_again(client, capsys):
    prompt = _answers(NEW_PASS, "outra-coisa", NEW_PASS, NEW_PASS)
    assert reset_password_cli.main([ADMIN_USER], prompt=prompt) == 0
    assert "As senhas não conferem." in capsys.readouterr().out
    assert len(prompt.prompts) == 4
    assert auth.verify_password(NEW_PASS, _user()["password_hash"])


def test_unknown_user_is_reported_without_prompting(client, capsys):
    prompt = _answers()
    assert reset_password_cli.main(["ninguem.aqui"], prompt=prompt) == 1
    assert prompt.prompts == []
    assert "Usuário não encontrado." in capsys.readouterr().err


def test_login_lookup_ignores_case_like_the_panel(client, capsys):
    # The panel's login lookup ignores case; the CLI finds the same account and
    # reports it by its stored spelling.
    assert reset_password_cli.main(["SECRETARIA"], prompt=_answers(NEW_PASS, NEW_PASS)) == 0
    assert f"Senha de '{ADMIN_USER}' redefinida." in capsys.readouterr().out
    assert auth.verify_password(NEW_PASS, _user()["password_hash"])


def test_password_is_never_accepted_as_an_argument(client):
    with pytest.raises(SystemExit) as exc:
        reset_password_cli.main([ADMIN_USER, NEW_PASS], prompt=_answers())
    assert exc.value.code == 2
    assert auth.verify_password(ADMIN_PASS, _user()["password_hash"])


def test_other_users_are_left_untouched(client, auth_headers):
    db.create_admin_user("outra.pessoa", auth.hash_password("Outra-Senha-2026!"), "secretaria")
    other_before = db.get_admin_user_by_username("outra.pessoa")
    assert reset_password_cli.main([ADMIN_USER], prompt=_answers(NEW_PASS, NEW_PASS)) == 0
    assert db.get_admin_user_by_username("outra.pessoa") == other_before
