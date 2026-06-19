import { useRef } from "react";
import { EditorAPI } from "../../hooks/useEditorCanvas";
import { uploadTemplateBackground } from "../../services/visualTemplateApi";

interface EditorTopbarProps {
  templateName: string;
  saving: boolean;
  hasBackground: boolean;
  showMockData: boolean;
  showGrid: boolean;
  zoom: number;
  onNameChange: (name: string) => void;
  onSave: () => void;
  onBack: () => void;
  onClearAll: EditorAPI["clearAll"];
  onSetMock: EditorAPI["setShowMockData"];
  onSetGrid: EditorAPI["setShowGrid"];
  onSetZoom: EditorAPI["setZoom"];
  onExport: EditorAPI["exportJSON"];
  onImport: EditorAPI["importJSON"];
  onBackgroundUploaded: (url: string, width: number, height: number) => void;
  onImageUploaded: (file: File) => void | Promise<void>;
}

function EditorTopbar({
  templateName,
  saving,
  hasBackground,
  showMockData,
  showGrid,
  zoom,
  onNameChange,
  onSave,
  onBack,
  onClearAll,
  onSetMock,
  onSetGrid,
  onSetZoom,
  onExport,
  onImport,
  onBackgroundUploaded,
  onImageUploaded,
}: EditorTopbarProps) {
  const bgInputRef = useRef<HTMLInputElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);
  const importInputRef = useRef<HTMLInputElement>(null);

  const handleBgUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    try {
      const result = await uploadTemplateBackground(file);
      onBackgroundUploaded(
        result.background_url,
        result.image_width,
        result.image_height,
      );
    } catch {
      alert("Erro ao enviar o background. Verifique o servidor.");
    }

    e.target.value = "";
  };

  const handleImageUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    try {
      await onImageUploaded(file);
    } catch {
      alert("Erro ao carregar imagem no editor.");
    }

    e.target.value = "";
  };

  const handleImportFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (ev) => {
      const json = ev.target?.result as string;
      if (json) onImport(json);
    };
    reader.readAsText(file);
    e.target.value = "";
  };

  const handleExport = () => {
    const json = onExport();
    const blob = new Blob([json], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${templateName || "template"}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="flex items-center gap-3 border-b border-slate-200 bg-white px-4 py-2.5">
      <button
        type="button"
        onClick={onBack}
        className="rounded-full border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-600 transition hover:border-slate-400 hover:bg-slate-50"
      >
        Voltar
      </button>

      <input
        type="text"
        value={templateName}
        onChange={(e) => onNameChange(e.target.value)}
        placeholder="Nome do template"
        className="w-48 rounded-lg border border-slate-200 px-3 py-1.5 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-sky-400"
      />

      <div className="h-5 w-px bg-slate-200" />

      <button
        type="button"
        onClick={() => bgInputRef.current?.click()}
        className="rounded-full border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 transition hover:border-sky-400 hover:bg-sky-50 hover:text-sky-700"
      >
        {hasBackground ? "Trocar fundo" : "Upload fundo"}
      </button>
      <input
        ref={bgInputRef}
        type="file"
        accept="image/png,image/jpeg"
        className="hidden"
        onChange={handleBgUpload}
      />

      <button
        type="button"
        onClick={() => imageInputRef.current?.click()}
        className="rounded-full border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 transition hover:border-sky-400 hover:bg-sky-50 hover:text-sky-700"
      >
        Upload imagem
      </button>
      <input
        ref={imageInputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={handleImageUpload}
      />

      <div className="flex-1" />

      <ToggleChip
        label="Preview"
        active={showMockData}
        onClick={() => onSetMock(!showMockData)}
      />
      <ToggleChip
        label="Grid"
        active={showGrid}
        onClick={() => onSetGrid(!showGrid)}
      />

      <div className="flex items-center gap-1.5">
        <button
          type="button"
          onClick={() => onSetZoom(Math.max(0.25, zoom - 0.25))}
          className="rounded border border-slate-200 px-2 py-1 text-xs text-slate-600 hover:bg-slate-100"
        >
          -
        </button>
        <span className="w-12 text-center text-xs font-medium text-slate-600">
          {Math.round(zoom * 100)}%
        </span>
        <button
          type="button"
          onClick={() => onSetZoom(Math.min(3, zoom + 0.25))}
          className="rounded border border-slate-200 px-2 py-1 text-xs text-slate-600 hover:bg-slate-100"
        >
          +
        </button>
      </div>

      <div className="h-5 w-px bg-slate-200" />

      <button
        type="button"
        onClick={() => importInputRef.current?.click()}
        className="rounded-full border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-600 transition hover:bg-slate-50"
      >
        Importar
      </button>
      <input
        ref={importInputRef}
        type="file"
        accept=".json,application/json"
        className="hidden"
        onChange={handleImportFile}
      />

      <button
        type="button"
        onClick={handleExport}
        className="rounded-full border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-600 transition hover:bg-slate-50"
      >
        Exportar
      </button>

      <button
        type="button"
        onClick={() => {
          if (confirm("Remover todos os elementos do canvas?")) onClearAll();
        }}
        className="rounded-full border border-rose-200 px-3 py-1.5 text-sm font-medium text-rose-600 transition hover:bg-rose-50"
      >
        Limpar
      </button>

      <button
        type="button"
        onClick={onSave}
        disabled={saving}
        className="rounded-full bg-sky-600 px-5 py-1.5 text-sm font-semibold text-white transition hover:bg-sky-500 disabled:cursor-not-allowed disabled:bg-slate-300"
      >
        {saving ? "Salvando..." : "Salvar"}
      </button>
    </div>
  );
}

function ToggleChip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "rounded-full border px-3 py-1.5 text-xs font-medium transition",
        active
          ? "border-sky-500 bg-sky-50 text-sky-700"
          : "border-slate-200 text-slate-500 hover:border-slate-400",
      ].join(" ")}
    >
      {label}
    </button>
  );
}

export default EditorTopbar;
