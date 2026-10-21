import { TemplateLayout } from "../types/template";
import { api } from "./api";

/** A version of the single global certificate template (immutable). */
export interface TemplateVersion {
  id: number;
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
  layout?: TemplateLayout;
}

export async function getActiveVersion(): Promise<TemplateVersion | null> {
  try {
    const res = await api.get<TemplateVersion>("/templates/active");
    return res.data;
  } catch {
    return null; // 404 when nothing is active yet
  }
}

export async function listVersions(): Promise<TemplateVersion[]> {
  const res = await api.get<TemplateVersion[]>("/templates/versions");
  return res.data;
}

export async function getVersion(id: number): Promise<TemplateVersion> {
  const res = await api.get<TemplateVersion>(`/templates/versions/${id}`);
  return res.data;
}

export async function createVersion(
  name: string,
  layout: TemplateLayout,
  certificateType: string | null = null,
): Promise<TemplateVersion> {
  const res = await api.post<TemplateVersion>("/templates/versions", {
    name,
    layout,
    certificate_type: certificateType || null,
  });
  return res.data;
}

export async function activateVersion(id: number): Promise<TemplateVersion> {
  const res = await api.post<TemplateVersion>(
    `/templates/versions/${id}/activate`,
  );
  return res.data;
}

export async function renameVersion(
  id: number,
  name: string,
): Promise<TemplateVersion> {
  const res = await api.patch<TemplateVersion>(`/templates/versions/${id}`, {
    name,
  });
  return res.data;
}

export async function deleteVersion(id: number): Promise<void> {
  await api.delete(`/templates/versions/${id}`);
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
