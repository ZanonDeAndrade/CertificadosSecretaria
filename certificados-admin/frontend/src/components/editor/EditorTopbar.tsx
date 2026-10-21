/**
 * Editor toolbar.
 *
 * Grouped by purpose (navigate · file · history · view · save) with hairline
 * separators, and it wraps onto a second row instead of overflowing — the old
 * single flex row pushed the save button off-screen on a 1366×768 notebook,
 * which is the machine this is actually used on.
 *
 * The primary action is separated from the destructive one, and "Limpar" is
 * never adjacent to "Salvar".
 */
import { useRef } from "react";
import { EditorAPI } from "../../hooks/useEditorCanvas";
import Button, { IconButton } from "../../ui/Button";
import Icon from "../../ui/Icon";
import { cn } from "../../ui/cn";

/** Read an image file as a data URL and resolve its natural pixel dimensions. */
function readImageAsDataUrl(
  file: File,
): Promise<{ dataUrl: string; width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Falha ao ler a imagem."));
    reader.onload = () => {
      const dataUrl = reader.result as string;
      const img = new Image();
      img.onload = () =>
        resolve({ dataUrl, width: img.naturalWidth, height: img.naturalHeight });
      img.onerror = () => reject(new Error("Imagem inválida."));
      img.src = dataUrl;
    };
    reader.readAsDataURL(file);
  });
}

const ZOOM_STEPS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3];

interface EditorTopbarProps {
  templateName: string;
  saving: boolean;
  hasBackground: boolean;
  isDirty: boolean;
  canUndo: boolean;
  canRedo: boolean;
  showMockData: boolean;
  showGrid: boolean;
  zoom: number;
  onNameChange: (name: string) => void;
  onSave: () => void;
  onBack: () => void;
  onUndo: () => void;
  onRedo: () => void;
  onRequestClear: () => void;
  onError: (message: string) => void;
  onSetMock: EditorAPI["setShowMockData"];
  onSetGrid: EditorAPI["setShowGrid"];
  onSetZoom: EditorAPI["setZoom"];
  onExport: EditorAPI["exportJSON"];
  onImport: EditorAPI["importJSON"];
  onBackgroundUploaded: (url: string, width: number, height: number) => void;
  onImageUploaded: (file: File) => void | Promise<void>;
  onShowShortcuts: () => void;
}

export default function EditorTopbar({
  templateName,
  saving,
  hasBackground,
  isDirty,
  canUndo,
  canRedo,
  showMockData,
  showGrid,
  zoom,
  onNameChange,
  onSave,
  onBack,
  onUndo,
  onRedo,
  onRequestClear,
  onError,
  onSetMock,
  onSetGrid,
  onSetZoom,
  onExport,
  onImport,
  onBackgroundUploaded,
  onImageUploaded,
  onShowShortcuts,
}: EditorTopbarProps) {
  const bgInputRef = useRef<HTMLInputElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);
  const importInputRef = useRef<HTMLInputElement>(null);

  const handleBgUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      // The background travels as a data URL inside the layout and is persisted
      // in the DB when the version is saved (never as a local file).
      const { dataUrl, width, height } = await readImageAsDataUrl(file);
      onBackgroundUploaded(dataUrl, width, height);
    } catch {
      onError("Erro ao carregar o fundo. Selecione um PNG ou JPG válido.");
    }
    event.target.value = "";
  };

  const handleImageUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      await onImageUploaded(file);
    } catch {
      onError("Erro ao carregar imagem no editor.");
    }
    event.target.value = "";
  };

  const handleImportFile = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (loaded) => {
      const json = loaded.target?.result as string;
      if (!json) return;
      try {
        onImport(json);
      } catch (error) {
        onError(error instanceof Error ? error.message : "JSON inválido ou malformado.");
      }
    };
    reader.readAsText(file);
    event.target.value = "";
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

  const stepZoom = (direction: 1 | -1) => {
    const currentIndex = ZOOM_STEPS.findIndex((step) => step >= zoom - 0.001);
    const nextIndex = Math.min(
      ZOOM_STEPS.length - 1,
      Math.max(0, (currentIndex === -1 ? 3 : currentIndex) + direction),
    );
    onSetZoom(ZOOM_STEPS[nextIndex]);
  };

  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-2 border-b border-[color:var(--line)] bg-[var(--surface)] px-3 py-2">
      <Button variant="ghost" size="sm" icon="chevron-left" onClick={onBack}>
        Voltar
      </Button>

      <Divider />

      <div className="flex min-w-0 items-center gap-2">
        <label
          htmlFor="template-name"
          className="whitespace-nowrap text-[length:var(--text-xs)] font-medium text-[color:var(--ink-muted)]"
        >
          Nome
        </label>
        <input
          id="template-name"
          type="text"
          value={templateName}
          onChange={(event) => onNameChange(event.target.value)}
          className={cn(
            "h-8 w-40 rounded-[var(--radius)] border border-[color:var(--line-strong)] bg-[var(--surface)] px-2.5",
            "text-[length:var(--text-sm)] text-[color:var(--ink)] lg:w-52",
          )}
        />
      </div>

      {isDirty && (
        <span className="inline-flex items-center gap-1.5 rounded-[var(--radius)] border border-[color:var(--warn-line)] bg-[var(--warn-bg)] px-2 py-1 text-[length:var(--text-xs)] font-medium text-[color:var(--warn-fg)]">
          <Icon name="warning" size={13} />
          Alterações não salvas
        </span>
      )}

      <Divider />

      <Button
        variant="secondary"
        size="sm"
        icon="image"
        onClick={() => bgInputRef.current?.click()}
      >
        {hasBackground ? "Trocar arte" : "Arte de fundo"}
      </Button>
      <input
        ref={bgInputRef}
        type="file"
        accept="image/png,image/jpeg"
        className="sr-only"
        onChange={handleBgUpload}
        aria-label="Arquivo da arte de fundo"
      />

      <Button
        variant="secondary"
        size="sm"
        icon="plus"
        onClick={() => imageInputRef.current?.click()}
      >
        Imagem
      </Button>
      <input
        ref={imageInputRef}
        type="file"
        accept="image/*"
        className="sr-only"
        onChange={handleImageUpload}
        aria-label="Arquivo de imagem para inserir"
      />

      <Divider />

      <div className="flex items-center gap-0.5">
        <IconButton
          size="sm"
          icon="undo"
          label="Desfazer (Ctrl+Z)"
          disabled={!canUndo}
          onClick={onUndo}
        />
        <IconButton
          size="sm"
          icon="redo"
          label="Refazer (Ctrl+Shift+Z)"
          disabled={!canRedo}
          onClick={onRedo}
        />
      </div>

      <Divider />

      <div className="flex items-center gap-0.5">
        <IconButton
          size="sm"
          icon="zoom-out"
          label="Diminuir zoom"
          disabled={zoom <= ZOOM_STEPS[0]}
          onClick={() => stepZoom(-1)}
        />
        <button
          type="button"
          onClick={() => onSetZoom(1)}
          title="Restaurar zoom para 100%"
          className="h-8 w-14 rounded-[var(--radius)] text-center text-[length:var(--text-xs)] font-medium tabular-nums text-[color:var(--ink-muted)] hover:bg-[var(--surface-inset)] hover:text-[color:var(--ink)]"
        >
          {Math.round(zoom * 100)}%
        </button>
        <IconButton
          size="sm"
          icon="zoom-in"
          label="Aumentar zoom"
          disabled={zoom >= ZOOM_STEPS[ZOOM_STEPS.length - 1]}
          onClick={() => stepZoom(1)}
        />
      </div>

      <Toggle
        label="Dados de exemplo"
        pressed={showMockData}
        icon="eye"
        onClick={() => onSetMock(!showMockData)}
      />
      <Toggle
        label="Grade"
        pressed={showGrid}
        icon="grid"
        onClick={() => onSetGrid(!showGrid)}
      />

      {/* Everything after this pushes right on wide screens. */}
      <div className="ml-auto flex flex-wrap items-center gap-2">
        <IconButton
          size="sm"
          icon="help"
          label="Atalhos de teclado"
          onClick={onShowShortcuts}
        />
        <Button
          variant="ghost"
          size="sm"
          icon="upload"
          onClick={() => importInputRef.current?.click()}
        >
          Importar
        </Button>
        <input
          ref={importInputRef}
          type="file"
          accept=".json,application/json"
          className="sr-only"
          onChange={handleImportFile}
          aria-label="Arquivo JSON do template"
        />
        <Button variant="ghost" size="sm" icon="download" onClick={handleExport}>
          Exportar
        </Button>
        <Button variant="danger-quiet" size="sm" icon="trash" onClick={onRequestClear}>
          Limpar
        </Button>

        <Divider />

        <Button
          variant="primary"
          size="sm"
          icon="save"
          onClick={onSave}
          loading={saving}
        >
          {saving ? "Salvando…" : "Salvar versão"}
        </Button>
      </div>
    </div>
  );
}

function Divider() {
  return <span aria-hidden="true" className="h-6 w-px shrink-0 bg-[var(--line)]" />;
}

function Toggle({
  label,
  pressed,
  icon,
  onClick,
}: {
  label: string;
  pressed: boolean;
  icon: "eye" | "grid";
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      className={cn(
        "inline-flex h-8 items-center gap-1.5 rounded-[var(--radius)] border px-2.5",
        "text-[length:var(--text-xs)] font-medium",
        pressed
          ? "border-[color:var(--brand-500)] bg-[var(--brand-50)] text-[color:var(--brand-800)]"
          : "border-[color:var(--line-strong)] bg-[var(--surface)] text-[color:var(--ink-muted)] hover:text-[color:var(--ink)]",
      )}
    >
      <Icon name={icon} size={14} />
      {label}
    </button>
  );
}
