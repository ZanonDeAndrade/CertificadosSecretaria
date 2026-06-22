"""Create (or update) a secretaria admin user.

Usage:
    python create_admin.py <username> <password> [role]

Reads the shared database (DATABASE_PATH). Passwords are stored as bcrypt
hashes — the plaintext is never persisted.
"""
from __future__ import annotations

import sys
from getpass import getpass

import auth
from database import db


def main(argv: list[str]) -> int:
    db.init_db()

    if len(argv) >= 3:
        username, password = argv[1], argv[2]
        role = argv[3] if len(argv) > 3 else "admin"
    else:
        username = input("Usuário: ").strip()
        password = getpass("Senha: ")
        confirm = getpass("Confirme a senha: ")
        if password != confirm:
            print("As senhas não conferem.")
            return 1
        role = "admin"

    if not username or not password:
        print("Usuário e senha são obrigatórios.")
        return 1

    if role not in auth.VALID_ROLES:
        print(f"Papel inválido. Use: {', '.join(sorted(auth.VALID_ROLES))}.")
        return 1

    existing = db.get_admin_user_by_username(username)
    if existing:
        print(f"Usuário '{username}' já existe (id={existing['id']}).")
        return 1

    user_id = db.create_admin_user(username, auth.hash_password(password), role)
    if user_id is None:
        print("Não foi possível criar o usuário.")
        return 1

    print(f"Usuário '{username}' criado com sucesso (id={user_id}, role={role}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
