/**
 * Editor toolbar.
 *
 * One row on the 1366×768 notebook this is used on, so the certificate below
 * keeps the height: navigation · name and type · art · history · view · save.
 * Rarely used actions (import, export, clear, shortcuts) live under "Mais".
 * The row still wraps on narrower windows instead of overflowing, and the
 * canvas refits whenever it does.
 *
 * The menu button opens the system navigation, which the editor hides to
 * give the page the whole viewport. The primary action is separated from the
 * destructive one: "Limpar" sits in the menu, never next to "Salvar".
 */
import { useRef } from "react";
import { EditorAPI } from "../../hooks/useEditorCanvas";
import Button, { IconButton } from "../../ui/Button";
import Icon from "../../ui/Icon";
import Menu from "../../ui/Menu";
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

interface EditorTopbarProps {
  templateName: string;
  /** "Ouvinte", "Genérico"… and "Direito"/"Todos os cursos", for the model button. */
  typeLabel: string;
  courseLabel: string;
  /** Opens the "Dados do modelo" dialog (name, type, course). */
  onOpenModelDetails: () => void;
  saving: boolean;
  hasBackground: boolean;
  isDirty: boolean;
  canUndo: boolean;
  canRedo: boolean;
  showMockData: boolean;
  showGrid: boolean;
  /** Whether the navigation drawer is open (for the menu button's state). */
  menuOpen: boolean;
  onOpenMenu: (trigger: HTMLElement) => void;
  onSave: () => void;
  onBack: () => void;
  onUndo: () => void;
  onRedo: () => void;
  onRequestClear: () => void;
  onError: (message: string) => void;
  onSetMock: EditorAPI["setShowMockData"];
  onSetGrid: EditorAPI["setShowGrid"];
  onExport: EditorAPI["exportJSON"];
  onImport: EditorAPI["importJSON"];
  onBackgroundUploaded: (url: string, width: number, height: number) => void;
  onShowShortcuts: () => void;
}

export default function EditorTopbar({
  templateName,
  typeLabel,
  courseLabel,
  onOpenModelDetails,
  saving,
  hasBackground,
  isDirty,
  canUndo,
  canRedo,
  showMockData,
  showGrid,
  menuOpen,
  onOpenMenu,
  onSave,
  onBack,
  onUndo,
  onRedo,
  onRequestClear,
  onError,
  onSetMock,
  onSetGrid,
  onExport,
  onImport,
  onBackgroundUploaded,
  onShowShortcuts,
}: EditorTopbarProps) {
  const bgInputRef = useRef<HTMLInputElement>(null);
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

  return (
    <div
      data-testid="editor-toolbar"
      className="flex flex-wrap items-center gap-x-1.5 gap-y-1.5 border-b border-[color:var(--line)] bg-[var(--surface)] px-2 py-2"
    >
      <IconButton
        size="sm"
        icon="menu"
        label="Abrir menu de navegação"
        aria-expanded={menuOpen}
        aria-controls="menu-navegacao"
        onClick={(event) => onOpenMenu(event.currentTarget)}
      />
      <Button variant="ghost" size="sm" icon="chevron-left" onClick={onBack}>
        Voltar
      </Button>

      <Divider />

      {/* Name, type and course live in a dialog: the toolbar keeps one row. */}
      <button
        type="button"
        onClick={onOpenModelDetails}
        title="Dados do modelo: nome, tipo e curso"
        className={cn(
          "flex h-8 min-w-0 max-w-[22rem] items-center gap-2 rounded-[var(--radius)] border px-2.5 text-left",
          "border-[color:var(--line-strong)] bg-[var(--surface)] hover:bg-[var(--surface-sunken)]",
        )}
      >
        <Icon name="template" size={14} className="shrink-0 text-[color:var(--ink-muted)]" />
        <span className="min-w-0 truncate text-[length:var(--text-sm)] font-medium text-[color:var(--ink)]">
          {templateName || "Novo modelo"}
        </span>
        <span className="hidden min-w-0 truncate text-[length:var(--text-xs)] text-[color:var(--ink-muted)] xl:inline">
          {typeLabel} · {courseLabel}
        </span>
        <span className="sr-only">Dados do modelo</span>
      </button>

      {isDirty && (
        <span
          title="Alterações não salvas"
          className="inline-flex h-8 items-center gap-1.5 rounded-[var(--radius)] border border-[color:var(--warn-line)] bg-[var(--warn-bg)] px-2 text-[length:var(--text-xs)] font-medium text-[color:var(--warn-fg)]"
        >
          <Icon name="warning" size={13} />
          Não salvo
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

      <Toggle
        label="Exemplo"
        title="Mostrar dados de exemplo no lugar das variáveis"
        pressed={showMockData}
        icon="eye"
        onClick={() => onSetMock(!showMockData)}
      />
      <Toggle
        label="Grade"
        title="Encaixar os elementos numa grade de 10 px da arte"
        pressed={showGrid}
        icon="grid"
        onClick={() => onSetGrid(!showGrid)}
      />

      {/* Everything after this pushes right. */}
      <div className="ml-auto flex items-center gap-1.5">
        <Menu
          label="Mais"
          size="sm"
          items={[
            {
              label: "Importar JSON",
              icon: "upload",
              onSelect: () => importInputRef.current?.click(),
            },
            { label: "Exportar JSON", icon: "download", onSelect: handleExport },
            { label: "Atalhos de teclado", icon: "help", onSelect: onShowShortcuts },
            {
              label: "Limpar elementos",
              icon: "trash",
              tone: "danger",
              onSelect: onRequestClear,
            },
          ]}
        />
        <input
          ref={importInputRef}
          type="file"
          accept=".json,application/json"
          className="sr-only"
          onChange={handleImportFile}
          aria-label="Arquivo JSON do template"
        />

        <Divider />

        <Button variant="primary" size="sm" icon="save" onClick={onSave} loading={saving}>
          {saving ? "Salvando…" : "Salvar"}
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
  title,
  pressed,
  icon,
  onClick,
}: {
  label: string;
  title: string;
  pressed: boolean;
  icon: "eye" | "grid";
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      title={title}
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
