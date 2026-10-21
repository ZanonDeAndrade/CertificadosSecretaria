"""Contracts for redacted secret scanning and professional release export."""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
import zipfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
from scripts import export_release as release_module
from scripts.security_scan import (
    prohibited_release_rule,
    scan_secret_permissions,
    scan_text,
    scan_zip,
)


def test_release_path_policy_excludes_secrets_data_and_runtime_files():
    blocked = {
        ".git/config",
        ".env.production",
        "secrets/service_account.json",
        "frontend/node_modules/pkg/index.js",
        "frontend/dist/index.html",
        "frontend/test-results/trace.zip",
        "frontend/playwright-report/index.html",
        "database/certificates.db-wal",
        "data/participants.xlsx",
        "output/certificate.pdf",
        "module (2).py",
        ".claude/launch.json",
    }
    assert all(prohibited_release_rule(path) for path in blocked)
    assert prohibited_release_rule(".env.production.example") is None
    assert prohibited_release_rule("database/models.py") is None


def test_secret_finding_output_is_redacted():
    marker = "Sensitive-Marker-987654321"
    findings = scan_text("fixture.env", "JWT_" + "SECRET=" + marker)
    assert findings
    rendered = findings[0].redacted()
    assert marker not in rendered
    assert rendered == "assigned-secret: fixture.env:1"


def test_operational_cloud_metadata_is_rejected_without_printing_value():
    host = "https://service-opaque-123.run" + ".app"
    findings = scan_text("deploy/config.json", host)
    assert any(item.rule == "operational-cloud-metadata" for item in findings)
    assert host not in "\n".join(item.redacted() for item in findings)


def test_artifact_scanner_rejects_git_metadata(tmp_path):
    artifact = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr(".git/config", "metadata")
    findings = scan_zip(artifact)
    assert any(finding.rule == "runtime-or-local-path" for finding in findings)


def test_release_export_contains_only_allowed_tracked_files(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "safe.py").write_text("print('synthetic')\n", encoding="utf-8")
    monkeypatch.setattr(release_module, "tracked_paths", lambda _root: ["safe.py"])
    monkeypatch.setattr(release_module, "tracked_modes", lambda _root: {"safe.py": "100644"})
    monkeypatch.setattr(release_module, "_archive_datetime", lambda _root: (2026, 1, 1, 0, 0, 0))
    artifact = tmp_path / "release.zip"
    included = release_module.export_release(artifact, root=source)
    assert included
    assert scan_zip(artifact) == []
    with zipfile.ZipFile(artifact) as archive:
        names = archive.namelist()
    assert not any(name == ".git" or name.startswith(".git/") for name in names)
    assert not any(prohibited_release_rule(name) for name in names)


def test_release_export_excludes_historical_documents(tmp_path, monkeypatch):
    source = tmp_path / "source"
    historical = source / "docs/historico"
    historical.mkdir(parents=True)
    (historical / "OBSOLETO.md").write_text("histórico\n", encoding="utf-8")
    (source / "README.md").write_text("atual\n", encoding="utf-8")
    monkeypatch.setattr(
        release_module,
        "tracked_paths",
        lambda _root: ["README.md", "docs/historico/OBSOLETO.md"],
    )
    monkeypatch.setattr(
        release_module,
        "tracked_modes",
        lambda _root: {"README.md": "100644", "docs/historico/OBSOLETO.md": "100644"},
    )
    monkeypatch.setattr(
        release_module,
        "_archive_datetime",
        lambda _root: (2026, 1, 1, 0, 0, 0),
    )
    artifact = tmp_path / "release.zip"

    included = release_module.export_release(artifact, root=source)

    assert included == ["README.md"]
    with zipfile.ZipFile(artifact) as archive:
        assert archive.namelist() == ["README.md"]


def test_permission_scanner_descends_into_secret_directory(tmp_path):
    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir(mode=0o700)
    secret_file = secret_dir / "jwt_secret"
    secret_file.write_text("synthetic", encoding="utf-8")
    secret_file.chmod(0o644)
    findings = scan_secret_permissions(tmp_path)
    assert any(item.rule == "secret-permissions-too-open" for item in findings)


def test_runtime_entrypoints_disable_raw_http_access_logs():
    """Legacy query strings must not reach Uvicorn access logs."""

    entrypoint = (_REPO_ROOT / "deploy" / "entrypoint.sh").read_text("utf-8")
    development = (_REPO_ROOT / "docker-compose.yml").read_text("utf-8")
    production = (_REPO_ROOT / "compose.production.yaml").read_text("utf-8")
    assert entrypoint.count("--no-access-log") == 2
    # Both Compose definitions use the image entrypoint; they do not replace
    # the Uvicorn command with an access-log-enabled variant.
    assert "APP_TARGET: admin" in development and "APP_TARGET: consulta" in development
    assert "APP_TARGET: admin" in production and "APP_TARGET: consulta" in production
    assert "uvicorn" not in development and "uvicorn" not in production


def test_cloudrun_image_has_no_environment_specific_api_host():
    dockerfile = (_REPO_ROOT / "deploy" / "Dockerfile.cloudrun-web").read_text("utf-8")
    assert ".run.app" not in dockerfile
    assert "ADMIN_API_HOST=" not in dockerfile
    assert "CONSULTA_API_HOST=" not in dockerfile


def test_alembic_preserves_postgres_only_trigram_index_in_drift_checks():
    env = (_REPO_ROOT / "database" / "migrations" / "env.py").read_text("utf-8")
    assert "idx_certificates_name_normalized_trgm" in env
    assert env.count("include_object=include_object") == 2


def test_toolchain_and_lockfiles_are_exact_and_synchronized():
    assert (_REPO_ROOT / ".python-version").read_text("utf-8").strip() == "3.12.13"
    assert (_REPO_ROOT / ".nvmrc").read_text("utf-8").strip() == "20.20.2"
    assert (_REPO_ROOT / ".node-version").read_text("utf-8").strip() == "20.20.2"

    frontend = _REPO_ROOT / "certificados-admin" / "frontend"
    package = json.loads((frontend / "package.json").read_text("utf-8"))
    lock = json.loads((frontend / "package-lock.json").read_text("utf-8"))
    locked_root = lock["packages"][""]
    assert package["packageManager"] == "npm@10.8.2"
    assert package["engines"] == {"node": "20.20.2", "npm": "10.8.2"}
    assert locked_root["dependencies"] == package["dependencies"]
    assert locked_root["devDependencies"] == package["devDependencies"]

    project = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text("utf-8"))
    assert project["project"]["requires-python"] == ">=3.12,<3.13"
    assert all("==" in dependency for dependency in project["project"]["dependencies"])
    for requirement_file in ("runtime.txt", "dev.txt", "ops.txt"):
        content = (_REPO_ROOT / "requirements" / requirement_file).read_text("utf-8")
        assert " --hash=sha256:" in content


def test_generated_dependencies_are_not_versioned():
    tracked = (
        subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=_REPO_ROOT,
            check=True,
            capture_output=True,
        )
        .stdout.decode("utf-8")
        .split("\0")
    )
    assert not any("node_modules/" in path for path in tracked)
    assert not any(path.endswith(".egg-info") or ".egg-info/" in path for path in tracked)


def test_python_packages_do_not_mutate_import_path():
    offenders = []
    for path in _REPO_ROOT.rglob("*.py"):
        relative = path.relative_to(_REPO_ROOT).as_posix()
        parts = path.relative_to(_REPO_ROOT).parts
        if ".venv" in parts or "tests" in parts or parts[:2] == ("database", "migrations"):
            continue
        if "sys.path" in path.read_text("utf-8"):
            offenders.append(relative)
    assert offenders == []


def test_synchronous_emission_cannot_start_work():
    backend = (_REPO_ROOT / "certificados-admin/backEnd/main.py").read_text("utf-8")
    frontend = (_REPO_ROOT / "certificados-admin/frontend/src/services/api.ts").read_text("utf-8")
    assert "removed_synchronous_generation" in backend
    assert "status_code=410" in backend
    assert '"/certificates/generate"' not in frontend
    assert '"/emission-batches"' in frontend


def test_ci_contains_every_blocking_gate_and_keeps_evidence():
    workflow = (_REPO_ROOT / ".github/workflows/ci.yml").read_text("utf-8")
    required_fragments = (
        "ruff check",
        "mypy ",
        "compileall",
        "alembic check",
        "pytest",
        "npm ci",
        "npm run typecheck",
        "npm test",
        "npm run build",
        "npm audit --audit-level=high",
        "gitleaks/gitleaks-action@",
        "playwright test",
        "docker/build-push-action@",
        "aquasecurity/trivy-action@",
        "anchore/sbom-action@",
        "required-gate:",
    )
    assert all(fragment in workflow for fragment in required_fragments)
    assert "continue-on-error" not in workflow
    assert "retention-days: 90" in workflow


def test_runtime_images_and_production_config_are_hardened():
    dockerfiles = [
        _REPO_ROOT / "Dockerfile",
        _REPO_ROOT / "deploy/Dockerfile.web",
        _REPO_ROOT / "deploy/Dockerfile.cloudrun-web",
    ]
    for path in dockerfiles:
        content = path.read_text("utf-8")
        assert "@sha256:" in content
        assert len(re.findall(r"^FROM ", content, re.MULTILINE)) >= 2
        assert "USER " in content

    compose = (_REPO_ROOT / "compose.production.yaml").read_text("utf-8")
    assert "read_only: true" in compose
    assert "cap_drop: [ALL]" in compose
    assert "postgres_ca" in compose
    assert "${APP_IMAGE:?" in compose and "${OPS_IMAGE:?" in compose

    cloudrun = (_REPO_ROOT / "deploy/cloudrun/deploy.sh").read_text("utf-8")
    assert "--ingress internal" in cloudrun
    assert "require_digest" in cloudrun
    assert "--timeout 120" in cloudrun
    assert "--no-traffic" in cloudrun


def test_operational_mechanisms_are_executable_configuration():
    jobs = (_REPO_ROOT / "deploy/cloudrun/configure-jobs.sh").read_text("utf-8")
    monitoring = (_REPO_ROOT / "deploy/cloudrun/configure-monitoring.sh").read_text("utf-8")
    assert jobs.count("gcloud run jobs deploy") == 5
    assert jobs.count("schedule_job ") >= 5
    assert "certificados-backup" in jobs
    assert monitoring.count("upsert_metric ") >= 5
    assert monitoring.count("upsert_policy ") >= 5
