#!/usr/bin/env python3
"""Create a deterministic academic-delivery ZIP from tracked source files."""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from scripts.security_scan import REPO_ROOT, prohibited_release_rule, scan_zip, tracked_paths

RELEASE_EXCLUDED_PREFIXES = ("docs/historico/",)


def tracked_modes(root: Path) -> dict[str, str]:
    """Return canonical file modes from the Git index, not the local filesystem."""

    result = subprocess.run(
        ["git", "ls-files", "--stage", "-z"],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
    )
    modes: dict[str, str] = {}
    for record in result.stdout.split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        mode = metadata.split(b" ", 1)[0].decode("ascii")
        modes[raw_path.decode("utf-8")] = mode
    return modes


def _archive_datetime(root: Path) -> tuple[int, int, int, int, int, int]:
    configured = (os.getenv("SOURCE_DATE_EPOCH") or "").strip()
    if configured:
        epoch = int(configured)
    else:
        result = subprocess.run(
            ["git", "show", "-s", "--format=%ct", "HEAD"],
            cwd=root,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        )
        epoch = int(result.stdout.strip())
    value = datetime.fromtimestamp(max(epoch, 315532800), tz=timezone.utc)
    return value.year, value.month, value.day, value.hour, value.minute, value.second


def export_release(output: Path, root: Path = REPO_ROOT) -> list[str]:
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"O destino já existe: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    included: list[str] = []
    archive_time = _archive_datetime(root)
    modes = tracked_modes(root)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative in tracked_paths(root):
            if relative.startswith(RELEASE_EXCLUDED_PREFIXES) or prohibited_release_rule(relative):
                continue
            source = root / relative
            if not source.is_file():
                continue
            info = zipfile.ZipInfo(relative, date_time=archive_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            executable = modes.get(relative) == "100755"
            info.external_attr = ((0o755 if executable else 0o644) & 0xFFFF) << 16
            # Only paths known by the Git index are eligible. Release generation
            # is required to run from a clean checkout, so these bytes correspond
            # exactly to the audited commit.
            archive.writestr(info, source.read_bytes(), compresslevel=9)
            included.append(relative)

    findings = scan_zip(output)
    if findings:
        output.unlink(missing_ok=True)
        redacted = ", ".join(f"{item.rule}:{item.path}" for item in findings[:10])
        raise RuntimeError(f"Artefato rejeitado pelo scanner: {redacted}")
    return included


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    try:
        included = export_release(args.output)
    except (OSError, RuntimeError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"export_error={type(exc).__name__}", file=sys.stderr)
        return 1
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    print(f"release_files={len(included)}")
    print(f"release_sha256={digest}")
    print(f"release_path={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
