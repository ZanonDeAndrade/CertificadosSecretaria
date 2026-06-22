"""Authorize a Google user and create the app-owned certificate folder.

This one-time utility is intended to run on a trusted workstation with a
browser. It uses the narrow ``drive.file`` scope, stores an offline refresh
token outside the repository, and creates a folder that the application can
access without requesting permission to the user's entire Drive.

Example:
    python authorize_google_drive.py \
        --client-file C:/secure/client_secret.json \
        --token-file C:/secure/certificados-oauth-token.json
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

for _ancestor in Path(__file__).resolve().parents:
    if (_ancestor / "storage_service" / "google_drive.py").is_file():
        if str(_ancestor) not in sys.path:
            sys.path.insert(0, str(_ancestor))
        break

from storage_service.google_drive import SCOPES  # noqa: E402


def authorize(
    *, client_file: Path, token_file: Path, folder_name: str, folder_id: str | None = None
) -> tuple[Path, str]:
    if not client_file.is_file():
        raise FileNotFoundError(f"Credencial OAuth não encontrada: {client_file}")

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError(
            "Dependências OAuth ausentes. Execute: "
            "python -m pip install -r certificados-admin/backEnd/requirements.txt"
        ) from exc

    flow = InstalledAppFlow.from_client_secrets_file(str(client_file), SCOPES)
    credentials = flow.run_local_server(
        host="localhost",
        port=0,
        open_browser=True,
        access_type="offline",
        prompt="consent",
        authorization_prompt_message=(
            "Abra esta URL no navegador para autorizar o Google Drive:\n{url}"
        ),
        success_message=(
            "Autorização concluída. Você pode fechar esta janela e voltar ao terminal."
        ),
    )
    if not credentials.refresh_token:
        raise RuntimeError(
            "O Google não retornou refresh_token. Revogue o acesso anterior ao app "
            "na Conta Google e execute novamente."
        )

    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(credentials.to_json(), encoding="utf-8")
    try:
        os.chmod(token_file, 0o600)
    except OSError:
        pass

    service = build("drive", "v3", credentials=credentials, cache_discovery=False)
    if folder_id:
        verified = service.files().get(fileId=folder_id, fields="id").execute()
        return token_file, verified["id"]

    created = (
        service.files()
        .create(
            body={
                "name": folder_name,
                "mimeType": "application/vnd.google-apps.folder",
            },
            fields="id",
        )
        .execute()
    )
    return token_file, created["id"]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Autoriza uma conta Google pessoal para armazenar certificados."
    )
    parser.add_argument(
        "--client-file",
        required=True,
        type=Path,
        help="JSON do cliente OAuth do tipo Aplicativo para computador.",
    )
    parser.add_argument(
        "--token-file",
        required=True,
        type=Path,
        help="Destino seguro, fora do repositório, para o token OAuth.",
    )
    parser.add_argument(
        "--folder-name",
        default="Certificados Secretaria",
        help="Nome da pasta privada que será criada no Meu Drive.",
    )
    parser.add_argument(
        "--folder-id",
        default=None,
        help="Reutiliza e valida uma pasta já criada, sem criar outra.",
    )
    args = parser.parse_args()

    token_path, folder_id = authorize(
        client_file=args.client_file.expanduser().resolve(),
        token_file=args.token_file.expanduser().resolve(),
        folder_name=args.folder_name.strip() or "Certificados Secretaria",
        folder_id=(args.folder_id or "").strip() or None,
    )
    print("Autorização OAuth concluída e pasta do Drive pronta.")
    print(f"Token salvo em: {token_path}")
    print(f"GOOGLE_DRIVE_CERTIFICATES_FOLDER_ID={folder_id}")
    print("GOOGLE_DRIVE_AUTH_MODE=oauth_user")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
