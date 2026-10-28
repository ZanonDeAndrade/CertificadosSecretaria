import axios from "axios";
import { filenameFromContentDisposition } from "../lib/contentDisposition";

export interface ValidationResult {
  valid: boolean;
  revoked?: boolean;
  status?: string;
  name?: string;
  event?: string;
  issued_at?: string;
  certificate_text?: string;
  date?: string;
  certificate_type?: string | null;
  certificate_type_label?: string;
  /** Per-work certificates belong to every author listed. */
  per_work?: boolean;
  authors?: string[];
  work_title?: string | null;
  team_name?: string | null;
}

// In production builds the API is reached at a same-origin "/api" prefix — a
// reverse proxy (Vercel rewrite in the cloud, nginx on the local server)
// forwards it to the admin backend. This keeps the auth cookie first-party in
// every browser. Dev falls back to the local backend. An explicit
// VITE_API_BASE_URL always wins.
export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL?.trim() ||
  (import.meta.env.PROD ? "/api" : "http://localhost:8000");

export const PUBLIC_API_BASE_URL =
  import.meta.env.VITE_PUBLIC_API_BASE_URL?.trim() ||
  (import.meta.env.PROD ? "/consulta-api" : "http://localhost:8001");

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 60000,
  withCredentials: true, // send/receive the HttpOnly auth cookie
});

export const SESSION_EXPIRED_EVENT = "certificados:session-expired";

api.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    if (axios.isAxiosError(error) && error.response?.status === 401) {
      const path = error.config?.url ?? "";
      if (!path.includes("/auth/login") && !path.includes("/auth/me")) {
        window.dispatchEvent(
          new CustomEvent(SESSION_EXPIRED_EVENT, {
            detail: getApiErrorMessage(error, "Sua sessão expirou. Entre novamente."),
          }),
        );
      }
    }
    return Promise.reject(error);
  },
);

export interface AdminUser {
  id: number;
  name: string;
  username: string;
  role: string;
  permissions: string[];
  must_change_password: boolean;
}

export async function login(
  username: string,
  password: string,
): Promise<AdminUser> {
  const response = await api.post<{ user: AdminUser }>("/auth/login", {
    username,
    password,
  });
  return response.data.user;
}

export async function logout(): Promise<void> {
  await api.post("/auth/logout");
}

export async function getMe(): Promise<AdminUser> {
  const response = await api.get<AdminUser>("/auth/me");
  return response.data;
}

export async function changeOwnPassword(
  currentPassword: string,
  newPassword: string,
): Promise<{ ok: boolean; sessions_revoked: number }> {
  const response = await api.post<{ ok: boolean; sessions_revoked: number }>(
    "/auth/change-password",
    { current_password: currentPassword, new_password: newPassword },
  );
  return response.data;
}

export interface PublicInstitutionSettings {
  institution_name: string;
  public_url: string;
}

export async function getPublicInstitutionSettings(): Promise<PublicInstitutionSettings> {
  const response = await api.get<PublicInstitutionSettings>("/institution");
  return response.data;
}

// ── Structured flow (spreadsheet → preview → generate) ──────────────────────

export interface PreviewRow {
  row_number: number;
  nome: string;
  curso: string;
  evento: string;
  /** Null when the type allows a blank workload (per-work certificates). */
  carga_horaria: number | null;
  data_emissao: string;
  data_inicio: string;
  data_fim: string;
  /** Per-work certificates: every author, the first being `nome`. */
  autores?: string[];
  equipe?: string;
  titulo_trabalho?: string;
}

export interface InvalidRow {
  row_number: number;
  errors: string[];
  data: Record<string, unknown>;
}

/** A sized text box of the active template that some participants overflow. */
export interface LayoutWarning {
  key: string;
  label: string;
  height: number;
  row_count: number;
  rows: { row_number: number; nome: string }[];
  /** Fixed text: it overflows for every certificate. */
  applies_to_all: boolean;
  checked_rows: number;
  /** The check stopped before the last valid row. */
  truncated: boolean;
}

/** An empty institutional setting that the active template prints. Blocks. */
export interface MissingSetting {
  setting: string;
  label: string;
  keys: string[];
}

/** A template field blank for some rows; those certificates omit it. Warns. */
export interface EmptyField {
  key: string;
  label: string;
  row_count: number;
  rows: { row_number: number; nome: string }[];
  checked_rows: number;
  truncated: boolean;
}

export interface SpreadsheetPreview {
  total: number;
  valid_count: number;
  invalid_count: number;
  valid: PreviewRow[];
  invalid: InvalidRow[];
  events: { key: string; label: string; count: number }[];
  /** Body text interpolated for the first valid row (preview before emission). */
  resolved_text_preview?: string | null;
  /** File-level notes, such as author columns beyond the supported eight. */
  warnings?: string[];
  layout_warnings?: LayoutWarning[];
  missing_settings?: MissingSetting[];
  missing_settings_message?: string | null;
  empty_fields?: EmptyField[];
  can_manage_settings?: boolean;
  /**
   * Blocks confirmation: a per-work type has no active template of its own,
   * or it prints the participant name, or lacks the authors block or body.
   */
  template_problem?: string | null;
  can_manage_templates?: boolean;
}

/**
 * `name` is the row's holder (the first author, for a per-work type). A
 * finished per-work batch also names each generated or duplicate work by its
 * title and every author, read back from the certificate.
 */
interface SummaryWork {
  row_number?: number;
  name: string;
  work_title?: string | null;
  authors?: string[];
}

export interface GenerationSummary {
  batch_id?: string;
  generated: (SummaryWork & { code: string })[];
  generated_count: number;
  duplicates: (SummaryWork & { existing_code: string })[];
  duplicate_count: number;
  failed: { row_number?: number; name: string; error: string }[];
  failed_count: number;
  invalid: { row_number: number; errors: string[] }[];
  invalid_count: number;
  total_rows: number;
}

export interface AdminCertificate {
  unique_code: string;
  participant_name: string;
  course_name?: string | null;
  event_name?: string | null;
  certificate_type?: string | null;
  certificate_type_label?: string;
  workload_hours?: number | null;
  /** Per-work certificates: every author, the first being `participant_name`. */
  authors?: string[];
  team_name?: string | null;
  work_title?: string | null;
  issue_date?: string | null;
  issue_date_iso?: string | null;
  status: string;
  download_available: boolean;
  integrity_status: string;
  integrity_blocked: boolean;
  storage_provider?: string | null;
  template_used?: string | null;
  template_version_id?: number | null;
  issued_by?: { id: number; name?: string | null; username?: string | null } | null;
  batch_id?: string | null;
  participant_email?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  file_size?: number | null;
  certificate_text?: string | null;
  revoked_at?: string | null;
  revoke_reason?: string | null;
  reissue_count?: number;
  reissued_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface CertificatesPage {
  items: AdminCertificate[];
  total: number;
  limit: number;
  offset: number;
}

export async function validateSpreadsheet(
  file: File,
  dataEmissao?: string,
  textoPadrao?: string,
  certificateType?: string,
): Promise<SpreadsheetPreview> {
  const formData = new FormData();
  formData.append("file", file);
  if (dataEmissao) formData.append("data_emissao", dataEmissao);
  if (textoPadrao !== undefined) formData.append("texto_padrao", textoPadrao);
  if (certificateType) formData.append("certificate_type", certificateType);
  const response = await api.post<SpreadsheetPreview>(
    "/certificates/validate-spreadsheet",
    formData,
    { headers: { "Content-Type": "multipart/form-data" } },
  );
  return response.data;
}

export interface ListCertificatesParams {
  name?: string;
  code?: string;
  course?: string;
  event?: string;
  certificate_type?: string;
  status?: string;
  date_from?: string;
  date_to?: string;
  batch_id?: string;
  limit?: number;
  offset?: number;
}

export async function listCertificates(
  params: ListCertificatesParams,
): Promise<CertificatesPage> {
  const response = await api.get<CertificatesPage>("/certificates", { params });
  return response.data;
}

export async function getCertificate(code: string): Promise<AdminCertificate> {
  const response = await api.get<AdminCertificate>(
    `/certificates/${encodeURIComponent(code)}`,
  );
  return response.data;
}

export async function revokeCertificate(
  code: string,
  reason: string,
): Promise<AdminCertificate> {
  const response = await api.post<AdminCertificate>(
    `/certificates/${encodeURIComponent(code)}/revoke`,
    { reason },
  );
  return response.data;
}

export interface BatchDownloadResult {
  blob: Blob;
  skippedCodes: string[];
}

export async function downloadCertificatesZip(
  codes: string[],
  onProgress?: (percent: number | null) => void,
): Promise<BatchDownloadResult> {
  try {
    const response = await api.post<Blob>(
      "/certificates/download-zip",
      { codes },
      {
        responseType: "blob",
        timeout: 120000,
        onDownloadProgress: (event) => {
          onProgress?.(
            event.total
              ? Math.min(100, Math.round((event.loaded / event.total) * 100))
              : null,
          );
        },
      },
    );
    const rawSkipped = response.headers["x-skipped-certificates"];
    const skippedCodes =
      typeof rawSkipped === "string" && rawSkipped
        ? decodeURIComponent(rawSkipped).split(",").filter(Boolean)
        : [];
    return { blob: response.data, skippedCodes };
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.data instanceof Blob) {
      try {
        const body = JSON.parse(await error.response.data.text()) as { detail?: string };
        if (body.detail) throw new Error(body.detail);
      } catch (parsedError) {
        if (parsedError instanceof Error && !(parsedError instanceof SyntaxError)) {
          throw parsedError;
        }
      }
    }
    throw error;
  }
}

export interface DownloadedFile {
  blob: Blob;
  /** Name suggested by the API (titular, evento e código), accents intact. */
  filename: string;
}

export async function downloadCertificateFile(code: string): Promise<DownloadedFile> {
  const response = await api.get<Blob>(
    `/certificate-file/${encodeURIComponent(code)}`,
    { responseType: "blob" },
  );
  return {
    blob: response.data,
    filename: filenameFromContentDisposition(
      response.headers["content-disposition"],
      `${code}.pdf`,
    ),
  };
}

export async function reissueCertificate(code: string): Promise<AdminCertificate> {
  const response = await api.post<AdminCertificate>(
    `/certificates/${encodeURIComponent(code)}/reissue`,
  );
  return response.data;
}

export function certificateFileUrl(code: string): string {
  return `${API_BASE_URL.replace(/\/$/, "")}/certificate-file/${encodeURIComponent(code)}`;
}

export async function validateCertificate(code: string): Promise<ValidationResult> {
  const response = await axios.get<{
    valid: boolean;
    status?: string;
    revoked?: boolean;
    certificate?: {
      participant_name?: string;
      event_name?: string | null;
      course_name?: string | null;
      issue_date?: string | null;
      certificate_type?: string | null;
      certificate_type_label?: string;
      per_work?: boolean;
      authors?: string[];
      work_title?: string | null;
      team_name?: string | null;
    };
  }>(
    `${PUBLIC_API_BASE_URL.replace(/\/$/, "")}/public/verify/${encodeURIComponent(code.trim())}`,
    { timeout: 60000 },
  );
  const payload = response.data;
  return {
    valid: payload.valid,
    revoked: payload.revoked,
    status: payload.status,
    name: payload.certificate?.participant_name,
    event: payload.certificate?.event_name ?? payload.certificate?.course_name ?? undefined,
    issued_at: payload.certificate?.issue_date ?? undefined,
    certificate_type: payload.certificate?.certificate_type,
    certificate_type_label: payload.certificate?.certificate_type_label,
    per_work: payload.certificate?.per_work,
    authors: payload.certificate?.authors,
    work_title: payload.certificate?.work_title,
    team_name: payload.certificate?.team_name,
  };
}

// ── Painel, usuários e auditoria ────────────────────────────────────────────

export interface DashboardStats {
  total: number;
  active: number;
  revoked: number;
  failed: number;
  pending: number;
  recent: number;
  recent_days: number;
  integrity_blocked: number;
  active_without_file: number;
}

export async function getDashboardStats(): Promise<DashboardStats> {
  const response = await api.get<DashboardStats>("/admin/stats");
  return response.data;
}

export async function getRecentCertificates(
  limit = 8,
): Promise<AdminCertificate[]> {
  const response = await api.get<AdminCertificate[]>("/admin/recent-certificates", {
    params: { limit },
  });
  return response.data;
}

export interface AdminUserRow {
  id: number;
  name: string;
  username: string;
  role: string;
  is_active: boolean;
  must_change_password: boolean;
  password_changed_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface AdminUsersPage {
  items: AdminUserRow[];
  total: number;
}

export interface CreateAdminUserInput {
  name: string;
  username: string;
  role: string;
  temporary_password: string;
}

export interface AdminUserMutation {
  user: AdminUserRow;
  sessions_revoked: number;
}

export async function listAdminUsers(): Promise<AdminUsersPage> {
  const response = await api.get<AdminUsersPage>("/admin/users");
  return response.data;
}

export async function createAdminUser(
  input: CreateAdminUserInput,
): Promise<AdminUserRow> {
  const response = await api.post<AdminUserRow>("/admin/users", input);
  return response.data;
}

export async function updateAdminUser(
  id: number,
  changes: { name?: string; username?: string; role?: string; is_active?: boolean },
): Promise<AdminUserMutation> {
  const response = await api.patch<AdminUserMutation>(`/admin/users/${id}`, changes);
  return response.data;
}

export async function setAdminUserActive(
  id: number,
  active: boolean,
): Promise<AdminUserMutation> {
  const response = await api.post<AdminUserMutation>(
    `/admin/users/${id}/${active ? "activate" : "deactivate"}`,
  );
  return response.data;
}

export async function resetAdminUserPassword(
  id: number,
  temporaryPassword: string,
): Promise<AdminUserMutation> {
  const response = await api.post<AdminUserMutation>(
    `/admin/users/${id}/reset-password`,
    { temporary_password: temporaryPassword },
  );
  return response.data;
}

export async function revokeAdminUserSessions(id: number): Promise<number> {
  const response = await api.post<{ revoked: number }>(
    `/admin/users/${id}/sessions/revoke-all`,
  );
  return response.data.revoked;
}

export interface AuditEntry {
  id: number;
  action: string;
  actor_id: number | null;
  actor_username: string | null;
  target_type: string | null;
  target_id: string | null;
  details: Record<string, unknown> | null;
  created_at?: string | null;
}

export interface AuditPage {
  items: AuditEntry[];
  total: number;
  limit: number;
  offset: number;
}

export interface AuditFilters {
  category?: string;
  action?: string;
  actor?: string;
  target_type?: string;
  target_id?: string;
  date_from?: string;
  date_to?: string;
  limit?: number;
  offset?: number;
}

export async function listAuditLog(params: AuditFilters): Promise<AuditPage> {
  const response = await api.get<AuditPage>("/admin/audit", { params });
  return response.data;
}

export interface InstitutionalSettings extends PublicInstitutionSettings {
  id: number;
  issue_location: string;
  signatory_name: string;
  signatory_title: string;
  retention_days: number;
  max_batch_rows: number;
  max_upload_mb: number;
  secretaria_can_revoke: boolean;
  secretaria_can_reissue: boolean;
  updated_at?: string | null;
  updated_by?: number | null;
}

export type InstitutionalSettingsInput = Omit<
  InstitutionalSettings,
  "id" | "updated_at" | "updated_by"
>;

export async function getInstitutionalSettings(): Promise<InstitutionalSettings> {
  const response = await api.get<InstitutionalSettings>("/admin/settings");
  return response.data;
}

export async function updateInstitutionalSettings(
  input: InstitutionalSettingsInput,
): Promise<InstitutionalSettings> {
  const response = await api.put<InstitutionalSettings>("/admin/settings", input);
  return response.data;
}

export type EmissionBatchStatus =
  | "queued"
  | "processing"
  | "completed"
  | "partial"
  | "failed"
  | "cancelled";

export interface EmissionBatch {
  id: string;
  status: EmissionBatchStatus;
  total_rows: number;
  valid_count: number;
  invalid_count: number;
  processed_count: number;
  generated_count: number;
  duplicate_count: number;
  failed_count: number;
  certificate_type?: string | null;
  certificate_type_label?: string;
  progress_percent: number;
  attempt_count?: number;
  max_attempts?: number;
  result: GenerationSummary | null;
  invalid_report: InvalidRow[];
  error_message: string | null;
  created_by: number | null;
  created_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  updated_at?: string | null;
}

export async function startEmissionBatch(
  file: File,
  idempotencyKey: string,
  certificateType: string,
  dataEmissao?: string,
  textoPadrao?: string,
  driveFolders: Record<string, string> = {},
): Promise<EmissionBatch> {
  const formData = new FormData();
  formData.append("file", file);
  if (dataEmissao) formData.append("data_emissao", dataEmissao);
  if (textoPadrao !== undefined) formData.append("texto_padrao", textoPadrao);
  formData.append("drive_folders_json", JSON.stringify(driveFolders));
  formData.append("certificate_type", certificateType);
  const response = await api.post<EmissionBatch>("/emission-batches", formData, {
    headers: {
      "Content-Type": "multipart/form-data",
      "Idempotency-Key": idempotencyKey,
    },
  });
  return response.data;
}

export interface GoogleDriveConnectionStatus {
  connected: boolean;
  account_email: string | null;
  expires_at: string | null;
  storage_provider?: "google_drive" | "local";
}

export interface GoogleDrivePickerSession {
  access_token: string;
  api_key: string;
  app_id: string | null;
  expires_at: string;
}

export async function getGoogleDriveStatus(): Promise<GoogleDriveConnectionStatus> {
  const response = await api.get<GoogleDriveConnectionStatus>(
    "/integrations/google-drive/status",
  );
  return response.data;
}

export async function startGoogleDriveOAuth(): Promise<string> {
  const response = await api.post<{ authorization_url: string }>(
    "/integrations/google-drive/oauth/start",
  );
  return response.data.authorization_url;
}

export async function getGoogleDrivePickerSession(): Promise<GoogleDrivePickerSession> {
  const response = await api.get<GoogleDrivePickerSession>(
    "/integrations/google-drive/picker-session",
  );
  return response.data;
}

export async function selectGoogleDriveFolder(
  folderId: string,
  event: string,
): Promise<{ folder_name: string; ready: boolean }> {
  const response = await api.post<{ folder_name: string; ready: boolean }>(
    "/integrations/google-drive/folders/select",
    { folder_id: folderId, event },
  );
  return response.data;
}

export async function disconnectGoogleDrive(): Promise<void> {
  await api.post("/integrations/google-drive/disconnect");
}

export async function getEmissionBatch(batchId: string): Promise<EmissionBatch> {
  const response = await api.get<EmissionBatch>(
    `/emission-batches/${encodeURIComponent(batchId)}`,
  );
  return response.data;
}

export async function resumeEmissionBatch(
  idempotencyKey: string,
): Promise<EmissionBatch> {
  const response = await api.get<EmissionBatch>(
    `/emission-batches/by-idempotency-key/${encodeURIComponent(idempotencyKey)}`,
  );
  return response.data;
}

export async function cancelEmissionBatch(batchId: string): Promise<EmissionBatch> {
  const response = await api.post<EmissionBatch>(
    `/emission-batches/${encodeURIComponent(batchId)}/cancel`,
  );
  return response.data;
}

export async function retryEmissionBatch(batchId: string): Promise<EmissionBatch> {
  const response = await api.post<EmissionBatch>(
    `/emission-batches/${encodeURIComponent(batchId)}/retry`,
  );
  return response.data;
}

export const spreadsheetTemplateUrl = `${API_BASE_URL.replace(/\/$/, "")}/certificates/spreadsheet-template`;

/** Model workbook for a certificate type (per-work types get the author columns). */
export function spreadsheetTemplateUrlFor(certificateType?: string | null): string {
  if (!certificateType) return spreadsheetTemplateUrl;
  return `${spreadsheetTemplateUrl}?certificate_type=${encodeURIComponent(certificateType)}`;
}

/** A variable the certificate body text accepts, such as `{{equipe}}`. */
export interface BodyVariable {
  name: string;
  token: string;
  label: string;
  /** Whether per-work types accept it (`{{nome}}` is the first author only). */
  per_work?: boolean;
}

export interface BodyVariables {
  variables: BodyVariable[];
  /** Body a per-work type prints when the batch brings no text of its own. */
  per_work_automatic_text?: string;
}

/**
 * The body-text variables, read from the backend's own allowlist so the insert
 * buttons can never offer a variable the validation rejects, nor miss one.
 */
export async function listBodyVariables(): Promise<BodyVariables> {
  const response = await api.get<BodyVariables>("/certificates/body-variables");
  return response.data;
}

/**
 * Classifies a failed request so screens can show the right recovery.
 * `offline` is distinguished from a server error because retrying without a
 * connection cannot work, and 403 from 401 because one needs a different
 * account and the other needs signing in again.
 */
export type RequestFailure =
  | "offline"
  | "unauthorized"
  | "forbidden"
  | "rate-limited"
  | "server";

export function classifyError(error: unknown): RequestFailure {
  if (axios.isAxiosError(error)) {
    if (!error.response) {
      return typeof navigator !== "undefined" && navigator.onLine === false
        ? "offline"
        : "server";
    }
    const status = error.response.status;
    if (status === 401) return "unauthorized";
    if (status === 403) return "forbidden";
    if (status === 429) return "rate-limited";
  }
  return "server";
}

export function getApiErrorMessage(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string" && detail.trim()) return detail;
    if (
      detail &&
      typeof detail === "object" &&
      typeof (detail as { message?: unknown }).message === "string"
    ) {
      const message = (detail as { message: string }).message.trim();
      if (message) return message;
    }
    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) => (typeof item?.msg === "string" ? item.msg : ""))
        .filter(Boolean);
      if (messages.length) return messages.join(" ");
    }
  }
  if (error instanceof Error && error.message.trim()) return error.message;
  return fallback;
}

export { api };
