-- Shared schema for CertificadosSecretaria.
-- Used by both projects (certificados-admin grava, certificados-consulta lê).
-- Safe to run repeatedly: every statement is idempotent.

CREATE TABLE IF NOT EXISTS certificates (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    unique_code         TEXT    NOT NULL UNIQUE,          -- ex: CERT-2026-AB1234
    participant_name    TEXT    NOT NULL,                 -- nome completo do aluno
    participant_email   TEXT,                             -- e-mail (opcional)
    participant_document TEXT,                            -- CPF/matrícula (opcional)
    course_name         TEXT,                             -- curso (lista canônica)
    event_name          TEXT    NOT NULL,                 -- nome do evento (legado: curso)
    workload_hours      INTEGER,                          -- carga horária (estruturada)
    issue_date          TEXT    NOT NULL,                 -- data de emissão (por extenso)
    start_date          TEXT,                             -- início do evento (opcional)
    end_date            TEXT,                             -- fim do evento (opcional)
    pdf_path            TEXT,                             -- caminho local relativo a STORAGE_DIR (legado/local)
    certificate_text    TEXT,                             -- texto completo do certificado (opcional)
    -- ── Storage metadata (ver storage_service) ──────────────────────────────
    storage_provider    TEXT    NOT NULL DEFAULT 'local', -- 'local' | 'google_drive'
    drive_file_id       TEXT,                             -- id do arquivo no Google Drive
    drive_folder_id     TEXT,                             -- id da pasta no Google Drive
    original_filename   TEXT,                             -- nome original do PDF gerado
    mime_type           TEXT    NOT NULL DEFAULT 'application/pdf',
    file_size           INTEGER,                          -- tamanho em bytes
    checksum_sha256     TEXT,                             -- hash do conteúdo (integridade)
    -- ── Lifecycle / auditoria ───────────────────────────────────────────────
    status              TEXT    NOT NULL DEFAULT 'ativo', -- 'ativo' | 'revogado'
    business_key        TEXT,                             -- chave de idempotência (hash)
    issued_by           INTEGER,                          -- admin_users.id
    revoked_at          TEXT,
    revoked_by          INTEGER,
    revoke_reason       TEXT,
    created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT
);

-- NOTE: os índices são criados em db.py (_ensure_indexes), DEPOIS da migração de
-- colunas, para funcionar também em bancos antigos que ainda não têm as colunas
-- novas (ex.: business_key, course_name).

-- ── Usuários administrativos (secretaria) ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS admin_users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,                       -- bcrypt
    role          TEXT    NOT NULL DEFAULT 'secretaria',
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ── Trilha de auditoria ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id       INTEGER,
    actor_username TEXT,
    action         TEXT    NOT NULL,                      -- login|generate|revoke|...
    target_type    TEXT,                                  -- certificate|template|...
    target_id      TEXT,                                  -- código/identificador
    details        TEXT,
    created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);
