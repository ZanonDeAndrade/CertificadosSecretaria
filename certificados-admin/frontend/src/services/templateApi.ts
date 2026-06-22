import { TemplateLayout } from "../types/template";
import { api } from "./api";

/** A version of the single global certificate template (immutable). */
export interface TemplateVersion {
  id: number;
  version_number: number;
  name: string | null;
  is_active: boolean;
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
): Promise<TemplateVersion> {
  const res = await api.post<TemplateVersion>("/templates/versions", {
    name,
    layout,
  });
  return res.data;
}

export async function activateVersion(id: number): Promise<TemplateVersion> {
  const res = await api.post<TemplateVersion>(
    `/templates/versions/${id}/activate`,
  );
  return res.data;
}
