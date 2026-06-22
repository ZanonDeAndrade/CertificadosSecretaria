import { useEffect, useState } from "react";
import EditorCanvas from "../components/editor/EditorCanvas";
import EditorTopbar from "../components/editor/EditorTopbar";
import ElementList from "../components/editor/ElementList";
import PropertiesPanel from "../components/editor/PropertiesPanel";
import AccessibleModal from "../components/AccessibleModal";
import { useEditorCanvas } from "../hooks/useEditorCanvas";
import {
  TemplateVersion,
  activateVersion,
  createVersion,
  getActiveVersion,
  getVersion,
  listVersions,
} from "../services/templateApi";
import { API_BASE_URL, getApiErrorMessage } from "../services/api";

type EditorMode = "list" | "edit";
type DialogState = {
  title: string;
  message: string;
  confirmLabel?: string;
  onConfirm?: () => void;
};

function bgUrl(version: TemplateVersion): string {
  return `${API_BASE_URL.replace(/\/$/, "")}${version.background_url}`;
}

function TemplateEditor() {
  const [mode, setMode] = useState<EditorMode>("list");
  const [versions, setVersions] = useState<TemplateVersion[]>([]);
  const [active, setActive] = useState<TemplateVersion | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");

  const [templateName, setTemplateName] = useState("Nova versão");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [dialog, setDialog] = useState<DialogState | null>(null);

  const editor = useEditorCanvas();

  const refreshList = async () => {
    setLoading(true);
    setLoadError("");
    try {
      const [list, act] = await Promise.all([listVersions(), getActiveVersion()]);
      setVersions(list);
      setActive(act);
    } catch (error) {
      setLoadError(getApiErrorMessage(error, "Não foi possível carregar o template. Tente novamente."));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (mode === "list") refreshList();
  }, [mode]);

  const openEditor = async (versionId: number | null, name: string) => {
    setSaveError("");
    setTemplateName(name);
    setMode("edit");
    if (versionId == null) {
      editor.clearAll();
      return;
    }
    try {
      const full = await getVersion(versionId);
      if (full.layout) editor.loadTemplate(full.layout);
    } catch (error) {
      setSaveError(getApiErrorMessage(error, "Não foi possível carregar a versão para edição."));
    }
  };

  const handleSave = async () => {
    const name = templateName.trim();
    const layout = editor.getLayout();
    if (!layout.background) {
      setSaveError("Faça upload de uma imagem de fundo antes de salvar.");
      return;
    }
    setSaving(true);
    setSaveError("");
    try {
      const created = await createVersion(name || "Nova versão", layout);
      setMode("list");
      await refreshList();
      // Surface the new (inactive) version so the user can activate it.
      setActive((prev) => prev);
      void created;
    } catch (error) {
      setSaveError(getApiErrorMessage(error, "Erro ao salvar a versão. Verifique o servidor e tente novamente."));
    } finally {
      setSaving(false);
    }
  };

  const handleActivate = async (id: number) => {
    try {
      await activateVersion(id);
      await refreshList();
    } catch (error) {
      setDialog({
        title: "Falha ao ativar versão",
        message: getApiErrorMessage(error, "Não foi possível ativar esta versão."),
      });
    }
  };

  const modal = (
    <AccessibleModal
      open={Boolean(dialog)}
      title={dialog?.title ?? "Aviso"}
      onClose={() => setDialog(null)}
      footer={
        <>
          {dialog?.onConfirm && (
            <button
              type="button"
              onClick={() => {
                dialog.onConfirm?.();
                setDialog(null);
              }}
              className="rounded-full bg-rose-700 px-5 py-2 text-sm font-semibold text-white"
            >
              {dialog.confirmLabel ?? "Confirmar"}
            </button>
          )}
          <button type="button" onClick={() => setDialog(null)} className="rounded-full border border-slate-300 px-4 py-2 text-sm">
            {dialog?.onConfirm ? "Cancelar" : "Fechar"}
          </button>
        </>
      }
    >
      <p className="text-sm text-slate-700">{dialog?.message}</p>
    </AccessibleModal>
  );

  // ── List view ──────────────────────────────────────────────────────────────
  if (mode === "list") {
    return (
      <>
      <section className="space-y-6">
        <div className="flex items-end justify-between">
          <div className="space-y-1">
            <p className="text-sm font-semibold uppercase tracking-[0.24em] text-sky-700">
              Template global
            </p>
            <h2 className="text-2xl font-semibold text-slate-950">
              Modelo único de certificado
            </h2>
            <p className="text-sm text-slate-500">
              Existe um único template global. Cada alteração cria uma{" "}
              <strong>nova versão imutável</strong>; ative a que deve valer para
              todos os certificados.
            </p>
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => openEditor(active ? active.id : null, active ? `Cópia de v${active.version_number}` : "Nova versão")}
              className="inline-flex items-center justify-center rounded-full border border-slate-300 px-4 py-2.5 text-sm font-medium text-slate-700 transition hover:border-sky-400 hover:bg-sky-50"
            >
              {active ? "Editar (nova versão)" : "Criar template"}
            </button>
          </div>
        </div>

        {loadError && (
          <div className="rounded-[1.5rem] border border-rose-200 bg-rose-50/90 p-4 text-sm font-medium text-rose-800">
            {loadError}
          </div>
        )}

        {loading ? (
          <p className="text-sm text-slate-500">Carregando…</p>
        ) : (
          <>
            {/* Active template */}
            <div className="rounded-[1.75rem] border border-slate-200/80 bg-white/90 p-5">
              <p className="mb-3 text-sm font-semibold text-slate-700">Versão ativa</p>
              {active ? (
                <div className="flex items-center gap-4">
                  <img
                    src={bgUrl(active)}
                    alt={`Versão ${active.version_number}`}
                    className="h-28 w-44 rounded-xl border border-slate-200 object-cover"
                  />
                  <div className="space-y-0.5">
                    <p className="font-semibold text-slate-900">
                      v{active.version_number}
                      {active.name ? ` — ${active.name}` : ""}
                    </p>
                    <span className="inline-flex rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-semibold text-emerald-700">
                      Ativa
                    </span>
                  </div>
                </div>
              ) : (
                <p className="text-sm text-slate-400">
                  Nenhuma versão ativa ainda. Crie e ative um template.
                </p>
              )}
            </div>

            {/* Version history */}
            <div className="rounded-[1.75rem] border border-slate-200/80 bg-white/90 p-5">
              <p className="mb-3 text-sm font-semibold text-slate-700">
                Histórico de versões
              </p>
              {versions.length === 0 ? (
                <p className="text-sm text-slate-400">Nenhuma versão criada ainda.</p>
              ) : (
                <ul className="divide-y divide-slate-100">
                  {versions.map((v) => (
                    <li
                      key={v.id}
                      className="flex items-center justify-between gap-3 py-3"
                    >
                      <div className="flex items-center gap-3">
                        <img
                          src={bgUrl(v)}
                          alt={`v${v.version_number}`}
                          className="h-12 w-20 rounded-lg border border-slate-200 object-cover"
                        />
                        <div>
                          <p className="text-sm font-semibold text-slate-900">
                            v{v.version_number}
                            {v.name ? ` — ${v.name}` : ""}
                          </p>
                          {v.created_at && (
                            <p className="text-xs text-slate-400">
                              {new Date(v.created_at).toLocaleString("pt-BR")}
                            </p>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        {v.is_active ? (
                          <span className="rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-semibold text-emerald-700">
                            Ativa
                          </span>
                        ) : (
                          <button
                            type="button"
                            onClick={() => handleActivate(v.id)}
                            className="rounded-full border border-emerald-300 px-3 py-1 text-xs font-medium text-emerald-700 transition hover:bg-emerald-50"
                          >
                            Ativar
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => openEditor(v.id, `Cópia de v${v.version_number}`)}
                          className="rounded-full border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 transition hover:bg-slate-50"
                        >
                          Editar
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </>
        )}
      </section>
      {modal}
      </>
    );
  }

  // ── Editor view ────────────────────────────────────────────────────────────
  return (
    <>
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
        onRequestClear={() =>
          setDialog({
            title: "Limpar editor",
            message: "Remover todos os elementos do canvas? Esta ação não pode ser desfeita.",
            confirmLabel: "Limpar elementos",
            onConfirm: editor.clearAll,
          })
        }
        onError={(message) => setDialog({ title: "Erro no editor", message })}
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

      {editor.canvasError && (
        <div className="flex items-center justify-between gap-4 border-b border-rose-200 bg-rose-50 px-4 py-2 text-sm font-medium text-rose-700">
          <span>{editor.canvasError}</span>
          <button
            type="button"
            onClick={editor.clearCanvasError}
            className="rounded-full border border-rose-300 px-3 py-1 text-xs hover:bg-rose-100"
          >
            Fechar
          </button>
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
          canvasRef={editor.canvasRef}
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
    {modal}
    </>
  );
}

export default TemplateEditor;
