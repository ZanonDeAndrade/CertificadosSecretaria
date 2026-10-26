"""Reset a panel user's password from the command line.

For when nobody who can sign in is available to reset it from the Users
screen. The new password is typed twice at a hidden prompt (``getpass``) and is
never accepted as an argument, environment variable or file, so it cannot end
up in shell history, process listings or logs.

The reset follows the panel's rules: the password policy of "Alterar senha",
bcrypt with the current parameters, every session of the user revoked, the
change required at the next login and an audit entry without any password
material, all in one transaction.

Usage (inside the admin image):
    certificados-reset-password <usuario>
"""

from __future__ import annotations

import argparse
import sys
from getpass import getpass
from typing import Callable

from certificados_backend import auth
from certificados_backend.services import user_service

from database import db
from database.models import utcnow
from database.repositories import AuthSessionRepository

AUDIT_ACTION = "user_password_reset_cli"
SESSION_REVOKE_REASON = "password_reset_cli"
MAX_ATTEMPTS = 3


def reset_password(username: str, new_password: str) -> int:
    """Store ``new_password`` for ``username``; return how many sessions were revoked."""
    user = db.get_admin_user_by_username(username)
    if not user:
        raise user_service.UserNotFound("Usuário não encontrado.")
    with db._session() as session:
        target = user_service._locked_target(session, int(user["id"]))
        try:
            auth.validate_new_password(new_password, username=target.username)
        except ValueError as exc:
            raise user_service.UserServiceError(str(exc)) from exc
        if auth.verify_password(new_password, target.password_hash):
            raise user_service.UserServiceError("A nova senha deve ser diferente da senha atual.")
        target.password_hash = auth.hash_password(new_password)
        target.must_change_password = 1
        target.password_changed_at = utcnow()
        target.updated_at = utcnow()
        revoked = AuthSessionRepository(session).revoke_all(target.id, SESSION_REVOKE_REASON)
        # No signed-in actor: the entry is recorded as a system action.
        user_service._audit(
            session,
            AUDIT_ACTION,
            actor={"id": None, "username": None},
            target_id=target.id,
            details={"scope": "cli", "session_count": revoked},
        )
    return revoked


def main(argv: list[str] | None = None, *, prompt: Callable[[str], str] = getpass) -> int:
    parser = argparse.ArgumentParser(
        prog="certificados-reset-password",
        description=(
            "Redefine a senha de um usuário do painel. A senha nova é pedida sem eco; "
            "nunca a passe como argumento."
        ),
    )
    parser.add_argument("usuario", help="login do usuário no painel")
    args = parser.parse_args(argv)

    db.init_db()
    username = args.usuario.strip()
    user = db.get_admin_user_by_username(username)
    if not user:
        print("Usuário não encontrado.", file=sys.stderr)
        return 1
    username = str(user["username"])  # the stored spelling (lookup ignores case)
    if not user.get("is_active"):
        print("Atenção: o usuário está inativo; o login continuará bloqueado até reativá-lo.")

    for _attempt in range(MAX_ATTEMPTS):
        password = prompt("Nova senha: ")
        confirm = prompt("Repita a nova senha: ")
        if password != confirm:
            print("As senhas não conferem. Tente de novo.")
            continue
        try:
            revoked = reset_password(username, password)
        except user_service.UserServiceError as exc:
            print(f"Senha recusada: {exc}")
            continue
        print(
            f"Senha de '{username}' redefinida. Sessões revogadas: {revoked}. "
            "No próximo login, o sistema pedirá para trocar a senha."
        )
        return 0

    print("Nenhuma alteração foi feita.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
