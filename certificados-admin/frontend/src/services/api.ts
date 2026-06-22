import axios from "axios";

export interface ValidationResult {
  valid: boolean;
  revoked?: boolean;
  status?: string;
  name?: string;
  event?: string;
  issued_at?: string;
  certificate_text?: string;
  date?: string;
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
  username: string;
  role?: string;
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

// ── Structured flow (spreadsheet → preview → generate) ──────────────────────

export interface PreviewRow {
  row_number: number;
  nome: string;
  curso: string;
  evento: string;
  carga_horaria: number;
  data_emissao: string;
  email: string;
  documento: string;
  data_inicio: string;
  data_fim: string;
}

export interface InvalidRow {
  row_number: number;
  errors: string[];
  data: Record<string, unknown>;
}

export interface SpreadsheetPreview {
  total: number;
  valid_count: number;
  invalid_count: number;
  valid: PreviewRow[];
  invalid: InvalidRow[];
  /** Body text interpolated for the first valid row (preview before emission). */
  resolved_text_preview?: string | null;
}

export interface GenerationSummary {
  generated: { name: string; code: string }[];
  generated_count: number;
  duplicates: { name: string; existing_code: string }[];
  duplicate_count: number;
  invalid: { row_number: number; errors: string[] }[];
  invalid_count: number;
  total_rows: number;
}

export interface AdminCertificate {
  unique_code: string;
  participant_name: string;
  course_name?: string | null;
  event_name?: string | null;
  workload_hours?: number | null;
  issue_date?: string | null;
  status: string;
  download_available: boolean;
  storage_provider?: string | null;
  created_at?: string | null;
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
): Promise<SpreadsheetPreview> {
  const formData = new FormData();
  formData.append("file", file);
  if (dataEmissao) formData.append("data_emissao", dataEmissao);
  if (textoPadrao !== undefined) formData.append("texto_padrao", textoPadrao);
  const response = await api.post<SpreadsheetPreview>(
    "/certificates/validate-spreadsheet",
    formData,
    { headers: { "Content-Type": "multipart/form-data" } },
  );
  return response.data;
}

export async function generateCertificatesFromSpreadsheet(
  file: File,
  dataEmissao?: string,
  textoPadrao?: string,
): Promise<GenerationSummary> {
  const formData = new FormData();
  formData.append("file", file);
  if (dataEmissao) formData.append("data_emissao", dataEmissao);
  if (textoPadrao !== undefined) formData.append("texto_padrao", textoPadrao);
  const response = await api.post<GenerationSummary>(
    "/certificates/generate",
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
  status?: string;
  limit?: number;
  offset?: number;
}

export async function listCertificates(
  params: ListCertificatesParams,
): Promise<CertificatesPage> {
  const response = await api.get<CertificatesPage>("/certificates", { params });
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

export async function downloadCertificateFile(code: string): Promise<Blob> {
  const response = await api.get<Blob>(
    `/certificate-file/${encodeURIComponent(code)}`,
    { responseType: "blob" },
  );
  return response.data;
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
  };
}

export function getApiErrorMessage(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string" && detail.trim()) return detail;
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
