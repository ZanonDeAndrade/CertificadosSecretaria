import { TemplateLayout, VisualTemplate } from "../types/template";
import { api } from "./api";

export interface BackgroundUploadResult {
  background_url: string;
  image_width: number;
  image_height: number;
}

// ── Background ────────────────────────────────────────────────────────────────

export async function uploadTemplateBackground(
  file: File,
): Promise<BackgroundUploadResult> {
  const form = new FormData();
  form.append("file", file);
  const res = await api.post<BackgroundUploadResult>(
    "/visual-templates/background",
    form,
    { headers: { "Content-Type": "multipart/form-data" } },
  );
  return res.data;
}

// ── CRUD ──────────────────────────────────────────────────────────────────────

export async function listVisualTemplates(): Promise<VisualTemplate[]> {
  const res = await api.get<VisualTemplate[]>("/visual-templates");
  return res.data;
}

export async function getVisualTemplate(id: string): Promise<VisualTemplate> {
  const res = await api.get<VisualTemplate>(`/visual-templates/${id}`);
  return res.data;
}

export async function createVisualTemplate(
  name: string,
  layout: TemplateLayout,
): Promise<VisualTemplate> {
  const res = await api.post<VisualTemplate>("/visual-templates", {
    name,
    layout,
  });
  return res.data;
}

export async function updateVisualTemplate(
  id: string,
  name: string,
  layout: TemplateLayout,
): Promise<VisualTemplate> {
  const res = await api.put<VisualTemplate>(`/visual-templates/${id}`, {
    name,
    layout,
  });
  return res.data;
}

export async function deleteVisualTemplate(id: string): Promise<void> {
  await api.delete(`/visual-templates/${id}`);
}
