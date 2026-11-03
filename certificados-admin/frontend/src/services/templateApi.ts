import { TemplateLayout } from "../types/template";
import { api } from "./api";

/** A revision of a certificate model (immutable once used or active). */
export interface TemplateVersion {
  id: number;
  template_id?: number | null;
  version_number: number;
  name: string | null;
  is_active: boolean;
  /** Type the version is dedicated to; null (or absent) means generic. */
  certificate_type?: string | null;
  image_width: number;
  image_height: number;
  background_url: string;
  created_at?: string | null;
  activated_at?: string | null;
  /** Set on history entries: the revision the editor opens. */
  is_current?: boolean;
  layout?: TemplateLayout;
}

/** A certificate model: one item in the list, with its current revision. */
export interface CertificateTemplate {
  id: number;
  name: string;
  certificate_type: string | null;
  certificate_type_label?: string | null;
  /** null = all courses. Only files the model; emission picks by type. */
  course_id: number | null;
  course_name?: string | null;
  is_active: boolean;
  is_archived: boolean;
  archived_at?: string | null;
  /** Bumped on every save; sent back so a stale editor is refused. */
  revision: number;
  current_version_id: number | null;
  version_number: number | null;
  image_width: number | null;
  image_height: number | null;
  background_url: string | null;
  /** Issued (active or revoked) certificates across every revision. */
  certificate_count: number;
  /** Any certificate row (including failed attempts) pointing at a revision. */
  reference_count: number;
  ever_activated: boolean;
  /** The type cannot change any more: duplicate instead. */
  type_locked: boolean;
  /** Saving still changes the current revision in place. */
  edits_in_place: boolean;
  created_at?: string | null;
  updated_at?: string | null;
  activated_at?: string | null;
  layout?: TemplateLayout;
}

/** What a save did to the layout. */
export type SaveOutcome = "unchanged" | "updated" | "revised" | "applied";

export interface TemplateListFilters {
  course_id?: number | null;
  /** Only the models filed under "all courses". */
  without_course?: boolean;
  /** A type value, or GENERIC_TYPE for the generic models only. */
  certificate_type?: string | null;
  include_archived?: boolean;
}

export const GENERIC_TYPE = "__generic__";

export interface Course {
  id: number;
  name: string;
  is_active: boolean;
}

export async function getActiveVersion(): Promise<TemplateVersion | null> {
  try {
    const res = await api.get<TemplateVersion>("/templates/active");
    return res.data;
  } catch {
    return null; // 404 when nothing is active yet
  }
}

export async function getVersion(id: number): Promise<TemplateVersion> {
  const res = await api.get<TemplateVersion>(`/templates/versions/${id}`);
  return res.data;
}

export async function listTemplates(
  filters: TemplateListFilters = {},
): Promise<CertificateTemplate[]> {
  const params: Record<string, string | number | boolean> = {};
  if (filters.course_id != null) params.course_id = filters.course_id;
  if (filters.without_course) params.without_course = true;
  if (filters.certificate_type) params.certificate_type = filters.certificate_type;
  if (filters.include_archived) params.include_archived = true;
  const res = await api.get<CertificateTemplate[]>("/templates", { params });
  return res.data;
}

export async function getTemplate(id: number): Promise<CertificateTemplate> {
  const res = await api.get<CertificateTemplate>(`/templates/${id}`);
  return res.data;
}

export interface TemplateCreateInput {
  name: string;
  layout: TemplateLayout;
  certificate_type: string | null;
  course_id: number | null;
}

export async function createTemplate(input: TemplateCreateInput): Promise<CertificateTemplate> {
  const res = await api.post<CertificateTemplate>("/templates", input);
  return res.data;
}

export interface TemplateSaveInput {
  name?: string;
  /** Present and null makes the model generic; absent keeps the type. */
  certificate_type?: string | null;
  /** Present and null files the model under all courses; absent keeps it. */
  course_id?: number | null;
  layout?: TemplateLayout;
  revision: number;
  /** Required when the model is active and the layout changed. */
  apply?: boolean;
}

export async function saveTemplate(
  id: number,
  input: TemplateSaveInput,
): Promise<CertificateTemplate & { outcome: SaveOutcome }> {
  const res = await api.put<CertificateTemplate & { outcome: SaveOutcome }>(
    `/templates/${id}`,
    input,
  );
  return res.data;
}

export async function duplicateTemplate(
  id: number,
  input: { name?: string; version_id?: number } = {},
): Promise<CertificateTemplate> {
  const res = await api.post<CertificateTemplate>(`/templates/${id}/duplicate`, input);
  return res.data;
}

export async function activateTemplate(id: number): Promise<CertificateTemplate> {
  const res = await api.post<CertificateTemplate>(`/templates/${id}/activate`);
  return res.data;
}

export type DeleteOutcome = "deleted" | "archived";

export async function deleteTemplate(
  id: number,
): Promise<{ outcome: DeleteOutcome; template_id: number }> {
  const res = await api.delete<{ outcome: DeleteOutcome; template_id: number }>(
    `/templates/${id}`,
  );
  return res.data;
}

export async function restoreTemplate(id: number): Promise<CertificateTemplate> {
  const res = await api.post<CertificateTemplate>(`/templates/${id}/restore`);
  return res.data;
}

export async function getTemplateHistory(id: number): Promise<TemplateVersion[]> {
  const res = await api.get<TemplateVersion[]>(`/templates/${id}/history`);
  return res.data;
}

export async function listCourses(includeInactive = true): Promise<Course[]> {
  const res = await api.get<Course[]>("/courses", {
    params: includeInactive ? {} : { include_inactive: false },
  });
  return res.data;
}

export async function createCourse(name: string): Promise<Course> {
  const res = await api.post<Course>("/courses", { name });
  return res.data;
}

export async function updateCourse(
  id: number,
  input: { name?: string; is_active?: boolean },
): Promise<Course> {
  const res = await api.patch<Course>(`/courses/${id}`, input);
  return res.data;
}

/** Sample values for the preview, resolved exactly as the PDF resolves them. */
export interface TemplateSampleData {
  values: Record<string, string>;
  /** Institutional settings that are empty right now. */
  empty_settings: { setting: string; label: string }[];
  can_manage_settings: boolean;
}

export async function getTemplateSampleData(): Promise<TemplateSampleData> {
  const res = await api.get<TemplateSampleData>("/templates/sample-data");
  return res.data;
}

/** A text element as the backend measures it (same keys as the layout JSON). */
export interface TextLayoutItemRequest {
  id: string;
  key: string;
  text: string;
  x: number;
  fontSize: number;
  fontFamily: string;
  bold: boolean;
  align: "left" | "center" | "right";
  width?: number;
  height?: number;
}

export interface TextLayoutItemResult {
  id: string;
  lines: string[];
  /** Effective size: the participant name shrinks to fit its box. */
  font_size: number;
  line_height: number;
  text_height: number;
  wrap_width: number | null;
  overflow: boolean;
  /** Legacy name centring: the first line starts at `y - top_offset`. */
  top_offset: number;
}

/**
 * Ask the backend where each text's lines break. It measures with the fonts
 * the PDF uses, so the preview wraps exactly where the certificate will.
 */
export async function computeTextLayouts(
  imageWidth: number,
  items: TextLayoutItemRequest[],
): Promise<TextLayoutItemResult[]> {
  const res = await api.post<{ items: TextLayoutItemResult[] }>("/templates/text-layout", {
    image_width: imageWidth,
    items,
  });
  return res.data.items;
}
