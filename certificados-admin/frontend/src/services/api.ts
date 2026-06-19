import axios from "axios";

export interface ValidationResult {
  valid: boolean;
  name?: string;
  event?: string;
  issued_at?: string;
  certificate_text?: string;
  date?: string;
}

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL?.trim() || "http://localhost:8000";

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 60000,
  withCredentials: true, // send/receive the HttpOnly auth cookie
});

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
): Promise<SpreadsheetPreview> {
  const formData = new FormData();
  formData.append("file", file);
  if (dataEmissao) formData.append("data_emissao", dataEmissao);
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
  templateId?: string,
): Promise<GenerationSummary> {
  const formData = new FormData();
  formData.append("file", file);
  if (dataEmissao) formData.append("data_emissao", dataEmissao);
  if (templateId) formData.append("template_id", templateId);
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

export async function reissueCertificate(code: string): Promise<AdminCertificate> {
  const response = await api.post<AdminCertificate>(
    `/certificates/${encodeURIComponent(code)}/reissue`,
  );
  return response.data;
}

export function certificateFileUrl(code: string): string {
  return `${API_BASE_URL.replace(/\/$/, "")}/certificate-file/${encodeURIComponent(code)}`;
}

// key is the normalised course name (e.g. "engenharia_civil"), value is the
// relative path stored on the server (e.g. "templates/abc123.png")
export type TemplateMap = Record<string, string>;

export async function getCourses(): Promise<string[]> {
  const response = await api.get<string[]>("/courses");
  return response.data;
}

export async function getTemplates(): Promise<TemplateMap> {
  const response = await api.get<TemplateMap>("/templates");
  return response.data;
}

export async function uploadTemplate(
  courseName: string,
  file: File,
): Promise<string> {
  const formData = new FormData();
  formData.append("course_name", courseName);
  formData.append("file", file);
  const response = await api.post<{ message: string; key: string }>(
    "/upload-template",
    formData,
    { headers: { "Content-Type": "multipart/form-data" } },
  );
  return response.data.message;
}

export async function validateCertificate(code: string): Promise<ValidationResult> {
  const response = await api.get<ValidationResult>(
    `/validate/${encodeURIComponent(code.trim())}`,
  );
  return response.data;
}

export { api };
