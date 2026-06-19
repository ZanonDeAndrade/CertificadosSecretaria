import { useEffect, useRef, useState } from "react";
import EditorCanvas from "../components/editor/EditorCanvas";
import EditorTopbar from "../components/editor/EditorTopbar";
import ElementList from "../components/editor/ElementList";
import PropertiesPanel from "../components/editor/PropertiesPanel";
import { useEditorCanvas } from "../hooks/useEditorCanvas";
import {
  createVisualTemplate,
  deleteVisualTemplate,
  listVisualTemplates,
  updateVisualTemplate,
} from "../services/visualTemplateApi";
import { VisualTemplate } from "../types/template";
import { API_BASE_URL } from "../services/api";

type EditorMode = "list" | "edit";

function TemplateEditor() {
  const [mode, setMode] = useState<EditorMode>("list");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [templateName, setTemplateName] = useState("Novo Template");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [templates, setTemplates] = useState<VisualTemplate[]>([]);
  const [loadingList, setLoadingList] = useState(false);
  const [loadError, setLoadError] = useState("");

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const editor = useEditorCanvas(canvasRef);

  // ── Load template list ────────────────────────────────────────────────────
  const refreshList = async () => {
    setLoadingList(true);
    setLoadError("");
    try {
      const list = await listVisualTemplates();
      setTemplates(list);
    } catch {
      setLoadError("Não foi possível carregar os templates. Tente novamente.");
    } finally {
      setLoadingList(false);
    }
  };

  useEffect(() => {
    if (mode === "list") refreshList();
  }, [mode]);

  // ── Open editor (new) ─────────────────────────────────────────────────────
  const handleNew = () => {
    editor.clearAll();
    setEditingId(null);
    setTemplateName("Novo Template");
    setSaveError("");
    setMode("edit");
  };

  // ── Open editor (existing) ────────────────────────────────────────────────
  const handleEdit = (tmpl: VisualTemplate) => {
    setEditingId(tmpl.id);
    setTemplateName(tmpl.name);
    setSaveError("");
    setMode("edit");
    editor.loadTemplate(tmpl.layout);
  };

  // ── Delete template ───────────────────────────────────────────────────────
  const handleDelete = async (id: string) => {
    if (!confirm("Excluir este template?")) return;
    try {
      await deleteVisualTemplate(id);
      setTemplates((prev) => prev.filter((t) => t.id !== id));
    } catch {
      alert("Erro ao excluir template.");
    }
  };

  // ── Save template ─────────────────────────────────────────────────────────
  const handleSave = async () => {
    const name = templateName.trim();
    if (!name) {
      setSaveError("Informe um nome para o template.");
      return;
    }
    const layout = editor.getLayout();
    if (!layout.background) {
      setSaveError("Faça upload de uma imagem de fundo antes de salvar.");
      return;
    }

    setSaving(true);
    setSaveError("");
    try {
      if (editingId) {
        const updated = await updateVisualTemplate(editingId, name, layout);
        setTemplates((prev) =>
          prev.map((t) => (t.id === editingId ? updated : t)),
        );
      } else {
        const created = await createVisualTemplate(name, layout);
        setEditingId(created.id);
        setTemplates((prev) => [...prev, created]);
      }
    } catch {
      setSaveError("Erro ao salvar. Verifique o servidor e tente novamente.");
    } finally {
      setSaving(false);
    }
  };

  // ── Render: list view ─────────────────────────────────────────────────────
  if (mode === "list") {
    return (
      <section className="space-y-6">
        <div className="flex items-end justify-between">
          <div className="space-y-1">
            <p className="text-sm font-semibold uppercase tracking-[0.24em] text-sky-700">
              Editor Visual
            </p>
            <h2 className="text-2xl font-semibold text-slate-950">
              Templates de certificado
            </h2>
          </div>
          <button
            type="button"
            onClick={handleNew}
            className="inline-flex items-center justify-center rounded-full bg-sky-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-sky-500"
          >
            + Novo template
          </button>
        </div>

        {loadError && (
          <div className="rounded-[1.5rem] border border-rose-200 bg-rose-50/90 p-4 text-sm font-medium text-rose-800">
            {loadError}
          </div>
        )}

        {loadingList ? (
          <p className="text-sm text-slate-500">Carregando…</p>
        ) : templates.length === 0 ? (
          <div className="rounded-[1.75rem] border border-dashed border-slate-300 p-10 text-center text-sm text-slate-400">
            Nenhum template criado ainda. Clique em &ldquo;Novo template&rdquo; para
            começar.
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2">
            {templates.map((tmpl) => (
              <TemplateCard
                key={tmpl.id}
                template={tmpl}
                onEdit={() => handleEdit(tmpl)}
                onDelete={() => handleDelete(tmpl.id)}
              />
            ))}
          </div>
        )}
      </section>
    );
  }

  // ── Render: editor view ───────────────────────────────────────────────────
  return (
    <div className="-mx-6 -my-12 flex h-screen flex-col md:-mx-10 md:-my-20">
      <EditorTopbar
        templateName={templateName}
        saving={saving}
        hasBackground={Boolean(editor.backgroundUrl)}
        showMockData={editor.showMockData}
        showGrid={editor.showGrid}
        zoom={editor.zoom}
        onNameChange={setTemplateName}
        onSave={handleSave}
        onBack={() => setMode("list")}
        onClearAll={editor.clearAll}
        onSetMock={editor.setShowMockData}
        onSetGrid={editor.setShowGrid}
        onSetZoom={editor.setZoom}
        onExport={editor.exportJSON}
        onImport={editor.importJSON}
        onBackgroundUploaded={(url, w, h) => editor.setBackground(url, w, h)}
        onImageUploaded={editor.addImageElement}
      />

      {saveError && (
        <div className="border-b border-rose-200 bg-rose-50 px-4 py-2 text-sm font-medium text-rose-700">
          {saveError}
        </div>
      )}

      <div className="flex flex-1 overflow-hidden">
        <ElementList
          elements={editor.elements}
          selectedId={editor.selectedId}
          onAdd={editor.addTextElement}
          onSelect={editor.selectElement}
          onDelete={editor.deleteElement}
          onDuplicate={editor.duplicateElement}
        />

        <EditorCanvas
          canvasRef={canvasRef}
          backgroundUrl={editor.backgroundUrl}
          zoom={editor.zoom}
        />

        <PropertiesPanel
          elements={editor.elements}
          selectedId={editor.selectedId}
          onUpdate={editor.updateElement}
          onDelete={editor.deleteElement}
          onDuplicate={editor.duplicateElement}
        />
      </div>
    </div>
  );
}

// ── Template card component ───────────────────────────────────────────────────

interface TemplateCardProps {
  template: VisualTemplate;
  onEdit: () => void;
  onDelete: () => void;
}

function TemplateCard({ template, onEdit, onDelete }: TemplateCardProps) {
  const bgUrl = template.layout?.background
    ? template.layout.background.startsWith("http")
      ? template.layout.background
      : `${API_BASE_URL}${template.layout.background}`
    : null;

  const elementCount = template.layout?.elements?.length ?? 0;
  const createdAt = new Date(template.created_at).toLocaleDateString("pt-BR");

  return (
    <article className="flex flex-col gap-4 overflow-hidden rounded-[1.75rem] border border-slate-200/80 bg-white/90 shadow-[0_10px_35px_rgba(15,23,42,0.06)]">
      {/* Thumbnail */}
      <div className="relative h-36 w-full overflow-hidden bg-slate-100">
        {bgUrl ? (
          <img
            src={bgUrl}
            alt={template.name}
            className="h-full w-full object-cover"
          />
        ) : (
          <div className="flex h-full items-center justify-center text-slate-300 text-sm">
            Sem imagem
          </div>
        )}
        <div className="absolute inset-0 bg-gradient-to-t from-black/30 to-transparent" />
        <span className="absolute bottom-2 left-3 text-xs font-medium text-white/90">
          {elementCount} elemento{elementCount !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Info + actions */}
      <div className="flex items-start justify-between gap-3 px-4 pb-4">
        <div className="space-y-0.5">
          <h3 className="font-semibold text-slate-950">{template.name}</h3>
          <p className="text-xs text-slate-400">Criado em {createdAt}</p>
        </div>
        <div className="flex shrink-0 gap-2">
          <button
            type="button"
            onClick={onEdit}
            className="rounded-full border border-slate-300 px-4 py-1.5 text-sm font-medium text-slate-700 transition hover:border-sky-400 hover:bg-sky-50 hover:text-sky-700"
          >
            Editar
          </button>
          <button
            type="button"
            onClick={onDelete}
            className="rounded-full border border-rose-200 px-4 py-1.5 text-sm font-medium text-rose-600 transition hover:bg-rose-50"
          >
            Excluir
          </button>
        </div>
      </div>
    </article>
  );
}

export default TemplateEditor;
