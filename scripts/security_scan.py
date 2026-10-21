#!/usr/bin/env python3
"""Redacted repository/artifact hygiene and secret scanner.

The scanner reports only a rule id, path and optional line number.  It never
prints a matched value.  Gitleaks remains the history-aware scanner in CI; use
``--history`` locally to invoke an installed gitleaks binary with redaction.
"""

from __future__ import annotations

import argparse
import os
import re
import stat
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parent.parent

RUNTIME_PARTS = {
    ".agents",
    ".cache",
    ".claude",
    ".codex",
    ".git",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".vscode",
    "__pycache__",
    "backups",
    "blob-report",
    "dist",
    "node_modules",
    "playwright-report",
    "secrets",
    "test-results",
    "venv",
}
DATA_SUFFIXES = {
    ".csv",
    ".db",
    ".db-shm",
    ".db-wal",
    ".log",
    ".pdf",
    ".pyc",
    ".sqlite",
    ".sqlite3",
    ".tsbuildinfo",
    ".xls",
    ".xlsx",
}
SAFE_RELEASE_PDFS = {"docs/RELATORIO_TECNICO_FINAL.pdf"}
REPOSITORY_ONLY_HISTORICAL_PDFS = {
    "docs/historico/Relatorio_Tecnico_Certificados_junho_2026_OBSOLETO.pdf"
}
BINARY_SUFFIXES = {
    ".eot",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".png",
    ".ttf",
    ".woff",
    ".woff2",
}
SECRET_NAME_RE = re.compile(
    r"(?:service[-_]?account|client[-_]?secret|oauth.*token|credentials?|private[-_]?key)",
    re.IGNORECASE,
)
OPERATIONAL_METADATA_RE = re.compile(
    r"(?:https://[A-Za-z0-9.-]+\.run\.app\b|"
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.iam\.gserviceaccount\.com\b)",
    re.IGNORECASE,
)
CONTENT_RULES = (
    (
        "private-key",
        re.compile(r"-----BEGIN[ ](?:RSA[ ]|EC[ ]|OPENSSH[ ])?PRIVATE[ ]KEY-----"),
    ),
    (
        "google-private-key",
        re.compile(r'"private_key"\s*:\s*"(?!(?:<|\$\{|example|test|dummy))', re.I),
    ),
    (
        "oauth-refresh-token",
        re.compile(r'"refresh_token"\s*:\s*"([^"\r\n]+)"', re.I),
    ),
    (
        "oauth-client-secret",
        re.compile(r'"client_secret"\s*:\s*"([^"\r\n]+)"', re.I),
    ),
    (
        "postgres-credential-url",
        re.compile(r"postgres(?:ql)?(?:\+psycopg)?://[^\s:/]+:([^\s@]+)@", re.I),
    ),
    (
        "assigned-secret",
        re.compile(
            r"^(?:JWT_SECRET|DOCUMENT_HASH_SECRET|ADMIN_(?:INITIAL_)?PASSWORD)[ \t]*=[ \t]*([^\s#]+)",
            re.I | re.M,
        ),
    ),
)
PLACEHOLDER_MARKERS = {
    "${",
    "<",
    "change",
    "client-secret",
    "ci-only",
    "development",
    "dummy",
    "example",
    "generate",
    "gerar",
    "placeholder",
    "refresh-token",
    "replace",
    "test",
    "troque",
    "your",
    "xxxx",
}


@dataclass(frozen=True)
class Finding:
    rule: str
    path: str
    line: int | None = None

    def redacted(self) -> str:
        suffix = f":{self.line}" if self.line is not None else ""
        return f"{self.rule}: {self.path}{suffix}"


def _normalized(path: str) -> PurePosixPath:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return PurePosixPath(normalized)


def is_example_env(path: str) -> bool:
    name = _normalized(path).name.lower()
    return name == ".env.example" or (name.startswith(".env.") and name.endswith(".example"))


def prohibited_release_rule(path: str) -> str | None:
    pure = _normalized(path)
    normalized = str(pure)
    lower_parts = {part.lower() for part in pure.parts}
    name = pure.name.lower()
    if " (2)" in pure.name:
        return "duplicate-copy"
    if lower_parts & RUNTIME_PARTS:
        return "runtime-or-local-path"
    if name == ".env" or (name.startswith(".env.") and not is_example_env(path)):
        return "environment-secret-file"
    if SECRET_NAME_RE.search(name) and not name.endswith(".example"):
        return "credential-filename"
    if name.endswith((".pem", ".key", ".p12")):
        return "private-key-file"
    for suffix in DATA_SUFFIXES:
        if name.endswith(suffix):
            if suffix == ".pdf" and normalized in SAFE_RELEASE_PDFS:
                continue
            return "generated-or-personal-data"
    return None


def _looks_placeholder(value: str) -> bool:
    lowered = value.strip().casefold()
    if not lowered:
        return True
    if lowered in {
        "cert",
        "env",
        "file",
        "p",
        "pass",
        "password",
        "senha",
        "u:p",
        "user:pass",
        "usuario:senha",
    }:
        return True
    return any(marker in lowered for marker in PLACEHOLDER_MARKERS)


def scan_text(path: str, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for rule, pattern in CONTENT_RULES:
        for match in pattern.finditer(text):
            captured = match.group(1) if match.lastindex else match.group(0)
            if _looks_placeholder(captured):
                continue
            line = text.count("\n", 0, match.start()) + 1
            findings.append(Finding(rule, path, line))
    if not (path.lower().endswith(".example") or "/tests/" in f"/{path.lower()}"):
        for match in OPERATIONAL_METADATA_RE.finditer(text):
            if _looks_placeholder(match.group(0)):
                continue
            line = text.count("\n", 0, match.start()) + 1
            findings.append(Finding("operational-cloud-metadata", path, line))
    return findings


def _scan_bytes(path: str, data: bytes) -> list[Finding]:
    if _normalized(path).suffix.lower() in BINARY_SUFFIXES or b"\x00" in data[:4096]:
        return []
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return []
    return scan_text(path, text)


def tracked_paths(root: Path = REPO_ROOT) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
    )
    return sorted(item.decode("utf-8") for item in result.stdout.split(b"\0") if item)


def scan_repository(root: Path = REPO_ROOT) -> list[Finding]:
    findings: list[Finding] = []
    for relative in tracked_paths(root):
        # Historical PDFs remain versioned for provenance but never enter the
        # release. The final technical PDF is explicitly eligible and is also
        # checked by the release/audit workflow through extracted text.
        rule = prohibited_release_rule(relative)
        if rule and relative not in REPOSITORY_ONLY_HISTORICAL_PDFS:
            findings.append(Finding(rule, relative))
            continue
        path = root / relative
        if not path.is_file() or path.stat().st_size > 5 * 1024 * 1024:
            continue
        findings.extend(_scan_bytes(relative, path.read_bytes()))
    return findings


def scan_zip(path: Path) -> list[Finding]:
    findings: list[Finding] = []
    try:
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                name = info.filename.rstrip("/")
                if not name:
                    continue
                pure = _normalized(name)
                if pure.is_absolute() or ".." in pure.parts:
                    findings.append(Finding("unsafe-archive-path", name))
                    continue
                rule = prohibited_release_rule(name)
                if rule:
                    findings.append(Finding(rule, name))
                    continue
                if info.file_size > 5 * 1024 * 1024:
                    continue
                findings.extend(_scan_bytes(name, archive.read(info)))
    except (OSError, zipfile.BadZipFile):
        return [Finding("invalid-zip", str(path))]
    return findings


def scan_secret_permissions(root: Path = REPO_ROOT) -> list[Finding]:
    findings: list[Finding] = []
    # Secret contents remain unread; only metadata is inspected. Unlike source
    # scans, this walk must descend into ``secrets/`` to verify file modes.
    excluded = RUNTIME_PARTS - {"secrets"}
    for current, directories, filenames in os.walk(root):
        directories[:] = [name for name in directories if name.lower() not in excluded]
        current_path = Path(current)
        if current_path.name.lower() == "secrets":
            relative_dir = current_path.relative_to(root).as_posix()
            try:
                directory_mode = stat.S_IMODE(current_path.stat().st_mode)
            except OSError:
                findings.append(Finding("secret-permission-unreadable", relative_dir))
            else:
                if directory_mode & 0o077:
                    findings.append(Finding("secret-directory-permissions-too-open", relative_dir))
        for filename in filenames:
            relative = (current_path / filename).relative_to(root).as_posix()
            pure = _normalized(relative)
            lower_parts = {part.lower() for part in pure.parts}
            sensitive = (
                (
                    (pure.name.lower() == ".env" or pure.name.lower().startswith(".env."))
                    and not is_example_env(relative)
                )
                or "secrets" in lower_parts
                or bool(SECRET_NAME_RE.search(pure.name))
            )
            if not sensitive:
                continue
            path = root / relative
            try:
                mode = stat.S_IMODE(path.stat().st_mode)
            except OSError:
                findings.append(Finding("secret-permission-unreadable", relative))
                continue
            if mode & 0o077:
                findings.append(Finding("secret-permissions-too-open", relative))
    return findings


def scan_git_history(root: Path = REPO_ROOT) -> list[Finding]:
    """Scan reachable textual diffs without ever echoing patch contents."""

    try:
        result = subprocess.run(
            [
                "gitleaks",
                "git",
                "--redact",
                "--no-banner",
                "--exit-code",
                "1",
                "--log-opts=HEAD",
            ],
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except FileNotFoundError:
        result = subprocess.run(
            [
                "git",
                "log",
                "HEAD",
                "--patch",
                "--no-color",
                "--no-ext-diff",
                "--format=commit:%H",
            ],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode != 0:
            return [Finding("history-scan-error", "git-history")]
        return _scan_bytes("git-history", result.stdout)
    if result.returncode == 0:
        return []
    return [Finding("gitleaks-history-detection-or-error", "history")]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", action="store_true")
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--permissions", action="store_true")
    parser.add_argument("--history", action="store_true")
    args = parser.parse_args(argv)
    if not any((args.repository, args.artifact, args.permissions, args.history)):
        args.repository = True

    findings: list[Finding] = []
    if args.repository:
        findings.extend(scan_repository())
    if args.artifact:
        findings.extend(scan_zip(args.artifact))
    if args.permissions:
        findings.extend(scan_secret_permissions())
    if args.history:
        findings.extend(scan_git_history())

    for finding in sorted(set(findings), key=lambda item: (item.path, item.line or 0, item.rule)):
        print(finding.redacted())
    print(f"security_scan_findings={len(findings)}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
