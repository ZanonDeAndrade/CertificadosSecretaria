/**
 * Template do certificado — version list and visual editor.
 *
 * Two views in one route. The list is the safe, default view; the editor is
 * entered deliberately. Key behaviours the brief asked for:
 *
 *  - Undo/redo (Ctrl+Z / Ctrl+Shift+Z) via useTemplateHistory.
 *  - An unsaved-changes guard on both browser exit and in-app "Voltar".
 *  - Zoom with keyboard shortcuts and a reset.
 *  - Activation of a version is confirmed with a typed phrase, because it
 *    changes every certificate issued from that moment on.
 *  - Versions can be compared side by side before activating one.
 *
 * Layout: on notebooks (≤1279px) the two side panels collapse into a tabbed
 * strip so the canvas keeps usable width at 1366×768.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import EditorCanvas from "../components/editor/EditorCanvas";
import EditorTopbar from "../components/editor/EditorTopbar";
import ElementList from "../components/editor/ElementList";
import PropertiesPanel from "../components/editor/PropertiesPanel";
import PerWorkNotice from "../components/editor/PerWorkNotice";
import SettingsNotice from "../components/editor/SettingsNotice";
import { certificateTypeLabel, isPerWorkType } from "../domain/certificateTypes";
import { perWorkStartingPoint } from "../domain/perWorkTemplate";
import { getTemplateSampleData, TemplateSampleData } from "../services/templateApi";
import AccessibleModal from "../components/AccessibleModal";
import ConfirmDialog from "../ui/ConfirmDialog";
import PageHeader from "../ui/PageHeader";
import Panel, { PanelHeader } from "../ui/Panel";
import Alert from "../ui/Alert";
import Button from "../ui/Button";
import Icon from "../ui/Icon";
import StatusBadge from "../ui/StatusBadge";
import { Field, TextInput } from "../ui/Field";
import { EmptyState, ErrorState, Skeleton } from "../ui/Feedback";
import { cn } from "../ui/cn";
import { useEditorCanvas } from "../hooks/useEditorCanvas";
import {
  useTemplateHistory,
  useUnsavedChangesWarning,
} from "../hooks/useTemplateHistory";
import { useAuth } from "../app/AuthContext";
import { useMediaQuery } from "../app/useMediaQuery";
import { failureMessage } from "../app/useAsyncData";
import {
  TemplateVersion,
  activateVersion,
  createVersion,
  deleteVersion,
  getVersion,
  listVersions,
  renameVersion,
} from "../services/templateApi";
import { API_BASE_URL } from "../services/api";

type EditorMode = "list" | "edit";

function bgUrl(version: TemplateVersion): string {
  return `${API_BASE_URL.replace(/\/$/, "")}${version.background_url}`;
}

/** "Genérico" or the type the version is dedicated to. */
function versionTypeLabel(version: Pick<TemplateVersion, "certificate_type">): string {
  return version.certificate_type
    ? certificateTypeLabel(version.certificate_type)
    : "Genérico (todos os tipos)";
}

function formatDate(value?: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? "—"
    : parsed.toLocaleString("pt-BR", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
}

export default function TemplateEditor() {
  const { can } = useAuth();
  const canManage = can("templates.manage");

  const [mode, setMode] = useState<EditorMode>("list");
  const [versions, setVersions] = useState<TemplateVersion[]>([]);
  const [active, setActive] = useState<TemplateVersion | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");

  const [templateName, setTemplateName] = useState("Nova versão");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [notice, setNotice] = useState("");

  const [message, setMessage] = useState<{ title: string; body: string } | null>(null);
  const [clearing, setClearing] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [activating, setActivating] = useState<TemplateVersion | null>(null);
  const [activateBusy, setActivateBusy] = useState(false);
  const [activateError, setActivateError] = useState("");
  const [renaming, setRenaming] = useState<TemplateVersion | null>(null);
  const [renameName, setRenameName] = useState("");
  const [renameBusy, setRenameBusy] = useState(false);
  const [renameError, setRenameError] = useState("");
  const [deleting, setDeleting] = useState<TemplateVersion | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const [compare, setCompare] = useState<TemplateVersion[] | null>(null);
  const [sample, setSample] = useState<TemplateSampleData | null>(null);
  const [sampleFailed, setSampleFailed] = useState(false);
  /* Type the version being edited is dedicated to; null = generic. */
  const [templateType, setTemplateType] = useState<string | null>(null);

  const editor = useEditorCanvas();
  const history = useTemplateHistory(editor);
  const isEditing = mode === "edit";
  useUnsavedChangesWarning(isEditing && history.isDirty);

  /* Every canvas mutation is routed through `noteUserEdit` so the history layer
   * can tell a real change apart from the layout settling after a load. Wrapped
   * here rather than inside useEditorCanvas to keep that hook (and its tests)
   * untouched. */
  const { noteUserEdit } = history;
  const edited = useCallback(
    <Args extends unknown[], R>(action: (...args: Args) => R) =>
      (...args: Args): R => {
        noteUserEdit();
        return action(...args);
      },
    [noteUserEdit],
  );

  const editorActions = useMemo(
    () => ({
      addTextElement: edited(editor.addTextElement),
      addImageElement: edited(editor.addImageElement),
      updateElement: edited(editor.updateElement),
      nudgeElement: edited(editor.nudgeElement),
      deleteElement: edited(editor.deleteElement),
      duplicateElement: edited(editor.duplicateElement),
      setBackground: edited(editor.setBackground),
      clearAll: edited(editor.clearAll),
      importJSON: edited(editor.importJSON),
    }),
    [
      edited,
      editor.addTextElement,
      editor.addImageElement,
      editor.updateElement,
      editor.nudgeElement,
      editor.deleteElement,
      editor.duplicateElement,
      editor.setBackground,
      editor.clearAll,
      editor.importJSON,
    ],
  );

  /* Below xl the side panels share one strip, so the canvas keeps its width. */
  const isWideEditor = useMediaQuery("(min-width: 1280px)", true);
  const [activeSidePanel, setActiveSidePanel] = useState<"elements" | "properties">(
    "elements",
  );

  const refreshList = useCallback(async () => {
    setLoading(true);
    setLoadError("");
    try {
      const list = await listVersions();
      setVersions(list);
      // The generic active version serves every type without one of its own.
      setActive(list.find((version) => version.is_active && !version.certificate_type) ?? null);
    } catch (error) {
      setLoadError(
        failureMessage(error, "Não foi possível carregar as versões do template."),
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => {
      if (!cancelled && mode === "list") void refreshList();
    });
    return () => {
      cancelled = true;
    };
  }, [mode, refreshList]);

  /* Sample values come from the backend so the preview shows what the PDF
   * will print, institutional data included. Without the backend the editor
   * keeps its built-in sample and says so. */
  const loadSampleData = async () => {
    try {
      const data = await getTemplateSampleData();
      editor.setSampleData(data.values);
      setSample(data);
      setSampleFailed(false);
    } catch {
      setSample(null);
      setSampleFailed(true);
    }
  };

  const openEditor = async (
    versionId: number | null,
    name: string,
    certificateType: string | null = null,
  ) => {
    setSaveError("");
    setTemplateName(name);
    setTemplateType(certificateType);
    setMode("edit");
    history.reset();
    // Whatever settles on the canvas next is the clean starting point, whether
    // that is an empty canvas or a loaded version.
    history.markNextAsBaseline();
    void loadSampleData();
    if (versionId == null) {
      editor.clearAll();
      return;
    }
    try {
      const full = await getVersion(versionId);
      if (full.layout) editor.loadTemplate(full.layout);
    } catch (error) {
      setSaveError(
        failureMessage(error, "Não foi possível carregar esta versão para edição."),
      );
    }
  };

  /* Choosing a per-work type turns the layout being edited (usually a copy of
   * the generic template) into that type's starting point: no participant
   * name, the body moved up, the authors block above the QR code. It is an
   * ordinary edit, so Ctrl+Z brings the previous layout back. */
  const handleCertificateTypeChange = (next: string | null) => {
    const entering = isPerWorkType(next) && !isPerWorkType(templateType);
    setTemplateType(next);
    if (!entering) return;
    const current = editor.getLayout();
    const start = perWorkStartingPoint(current);
    if (JSON.stringify(start) === JSON.stringify(current)) return;
    noteUserEdit();
    editor.loadTemplate(start);
  };

  const handleSave = async () => {
    const name = templateName.trim();
    const layout = editor.getLayout();
    if (!layout.background) {
      setSaveError("Envie a arte de fundo antes de salvar a versão.");
      return;
    }
    setSaving(true);
    setSaveError("");
    try {
      await createVersion(name || "Nova versão", layout, templateType);
      history.markSaved();
      setMode("list");
      setNotice(
        "Nova versão salva. Ela ainda não está ativa — ative-a quando quiser que valha para as próximas emissões.",
      );
      await refreshList();
    } catch (error) {
      setSaveError(failureMessage(error, "Erro ao salvar a versão."));
    } finally {
      setSaving(false);
    }
  };

  const handleActivate = async () => {
    if (!activating) return;
    setActivateBusy(true);
    setActivateError("");
    try {
      await activateVersion(activating.id);
      setActivating(null);
      setNotice(
        `Versão ${activating.version_number} ativada. Os próximos certificados usarão este layout.`,
      );
      await refreshList();
    } catch (error) {
      setActivateError(failureMessage(error, "Não foi possível ativar esta versão."));
    } finally {
      setActivateBusy(false);
    }
  };

  const handleRename = async () => {
    if (!renaming) return;
    const cleanName = renameName.trim();
    if (!cleanName) {
      setRenameError("Informe um nome para a versão.");
      return;
    }
    setRenameBusy(true);
    setRenameError("");
    try {
      await renameVersion(renaming.id, cleanName);
      setRenaming(null);
      setNotice(`Versão ${renaming.version_number} renomeada com sucesso.`);
      await refreshList();
    } catch (error) {
      setRenameError(failureMessage(error, "Não foi possível renomear esta versão."));
    } finally {
      setRenameBusy(false);
    }
  };

  const handleDelete = async () => {
    if (!deleting) return;
    setDeleteBusy(true);
    setDeleteError("");
    try {
      await deleteVersion(deleting.id);
      setDeleting(null);
      setNotice(`Versão ${deleting.version_number} excluída.`);
      await refreshList();
    } catch (error) {
      setDeleteError(failureMessage(error, "Não foi possível excluir esta versão."));
    } finally {
      setDeleteBusy(false);
    }
  };

  const requestBack = () => {
    if (history.isDirty) setLeaving(true);
    else setMode("list");
  };

  /* Keyboard shortcuts — only while the editor view is open, and never while
   * the operator is typing into a field. */
  useEffect(() => {
    if (!isEditing) return;
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing =
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.tagName === "SELECT" ||
          target.isContentEditable);

      const mod = event.ctrlKey || event.metaKey;

      /* Arrow keys nudge the selected element: 1 px, or 10 px with Shift.
       * A field keeps its own cursor movement, and the element list keeps its
       * own navigation (it has already handled, and prevented, the event). */
      const arrows: Record<string, [number, number]> = {
        ArrowLeft: [-1, 0],
        ArrowRight: [1, 0],
        ArrowUp: [0, -1],
        ArrowDown: [0, 1],
      };
      const arrow = arrows[event.key];
      if (arrow && !mod && !event.altKey) {
        if (typing || event.defaultPrevented || !editor.selectedId) return;
        event.preventDefault();
        const step = event.shiftKey ? 10 : 1;
        editorActions.nudgeElement(editor.selectedId, arrow[0] * step, arrow[1] * step);
        return;
      }

      if (mod && event.key.toLowerCase() === "z") {
        if (typing) return;
        event.preventDefault();
        if (event.shiftKey) history.redo();
        else history.undo();
        return;
      }
      if (mod && event.key.toLowerCase() === "y") {
        if (typing) return;
        event.preventDefault();
        history.redo();
        return;
      }
      if (mod && event.key.toLowerCase() === "s") {
        event.preventDefault();
        void handleSave();
        return;
      }
      if (mod && (event.key === "=" || event.key === "+")) {
        event.preventDefault();
        editor.setZoom(Math.min(3, editor.zoom + 0.25));
        return;
      }
      if (mod && event.key === "-") {
        event.preventDefault();
        editor.setZoom(Math.max(0.25, editor.zoom - 0.25));
        return;
      }
      if (mod && event.key === "0") {
        event.preventDefault();
        editor.setZoom(1);
        return;
      }
      if (event.key === "?" && !typing) {
        event.preventDefault();
        setShortcutsOpen(true);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isEditing, history, editor.zoom, editor.selectedId, editorActions]);

  /* ── List view ──────────────────────────────────────────────────────── */
  if (mode === "list") {
    return (
      <>
        <PageHeader
          title="Template do certificado"
          description="O template genérico vale para todos os tipos; um tipo pode ter a própria versão ativa. Cada alteração cria uma nova versão imutável; ative a que deve valer para as próximas emissões."
          actions={
            canManage ? (
              <Button
                variant="primary"
                icon={active ? "duplicate" : "plus"}
                onClick={() =>
                  openEditor(
                    active ? active.id : null,
                    active ? `Cópia de v${active.version_number}` : "Nova versão",
                  )
                }
              >
                {active ? "Editar (nova versão)" : "Criar template"}
              </Button>
            ) : undefined
          }
        />

        {notice && (
          <Alert tone="ok" className="mb-4">
            {notice}
          </Alert>
        )}

        {loadError && (
          <Panel className="mb-4">
            <ErrorState description={loadError} onRetry={refreshList} />
          </Panel>
        )}

        {!canManage && (
          <Alert tone="info" live={false} className="mb-4">
            Seu perfil permite consultar o template, mas não criar nem ativar
            versões.
          </Alert>
        )}

        {/* Active version */}
        <Panel className="mb-4">
          <PanelHeader
            title="Versão ativa (genérica)"
            description="Usada por todos os tipos de certificado que não têm uma versão própria ativa."
          />
          <div className="px-4 py-4 sm:px-5">
            {loading ? (
              <div className="flex gap-4">
                <Skeleton className="h-28 w-44" />
                <div className="flex-1 space-y-2">
                  <Skeleton width="12rem" />
                  <Skeleton width="8rem" />
                </div>
              </div>
            ) : active ? (
              <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
                <img
                  src={bgUrl(active)}
                  alt={`Arte de fundo da versão ${active.version_number}`}
                  className="h-28 w-full max-w-[16rem] rounded-[var(--radius)] border border-[color:var(--line)] object-contain sm:w-44"
                />
                <div className="min-w-0">
                  <p className="text-[length:var(--text-md)] font-semibold text-[color:var(--ink)]">
                    Versão {active.version_number}
                    {active.name ? ` — ${active.name}` : ""}
                  </p>
                  <div className="mt-1.5">
                    <StatusBadge tone="ok">Ativa (genérica)</StatusBadge>
                  </div>
                  <dl className="mt-3 space-y-1 text-[length:var(--text-sm)] text-[color:var(--ink-muted)]">
                    <div className="flex gap-2">
                      <dt>Criada em:</dt>
                      <dd className="text-[color:var(--ink)]">{formatDate(active.created_at)}</dd>
                    </div>
                    <div className="flex gap-2">
                      <dt>Ativada em:</dt>
                      <dd className="text-[color:var(--ink)]">
                        {formatDate(active.activated_at)}
                      </dd>
                    </div>
                    <div className="flex gap-2">
                      <dt>Dimensões:</dt>
                      <dd className="text-[color:var(--ink)]">
                        {active.image_width} × {active.image_height} px
                      </dd>
                    </div>
                  </dl>
                </div>
              </div>
            ) : (
              <EmptyState
                icon="template"
                title="Nenhuma versão ativa"
                description="Sem um template ativo os certificados não podem ser gerados. Crie um template e ative-o."
                action={
                  canManage ? (
                    <Button
                      variant="primary"
                      icon="plus"
                      onClick={() => openEditor(null, "Nova versão")}
                    >
                      Criar template
                    </Button>
                  ) : undefined
                }
              />
            )}
          </div>
        </Panel>

        {/* Version history */}
        <Panel>
          <PanelHeader
            title="Histórico de versões"
            description="Versões anteriores são preservadas. Compare duas lado a lado antes de ativar."
            actions={
              versions.length > 1 ? (
                <Button
                  variant="secondary"
                  size="sm"
                  icon="eye"
                  onClick={() => setCompare(versions.slice(0, 2))}
                >
                  Comparar versões
                </Button>
              ) : undefined
            }
          />

          {loading ? (
            <div className="space-y-3 px-4 py-4 sm:px-5">
              {[0, 1, 2].map((row) => (
                <Skeleton key={row} className="h-14" />
              ))}
            </div>
          ) : versions.length === 0 ? (
            <EmptyState
              icon="template"
              title="Nenhuma versão criada"
              description="A primeira versão aparecerá aqui assim que você salvar o template."
            />
          ) : (
            <ul className="divide-y divide-[color:var(--line)]">
              {versions.map((version) => (
                <li
                  key={version.id}
                  className="flex flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:px-5"
                >
                  <img
                    src={bgUrl(version)}
                    alt=""
                    className="h-14 w-24 shrink-0 rounded-[var(--radius)] border border-[color:var(--line)] object-contain"
                  />
                  <div className="min-w-0 flex-1">
                    <p className="font-medium text-[color:var(--ink)]">
                      Versão {version.version_number}
                      {version.name ? ` — ${version.name}` : ""}
                    </p>
                    <p className="mt-0.5 text-[length:var(--text-xs)] text-[color:var(--ink-muted)]">
                      {versionTypeLabel(version)} · Criada em {formatDate(version.created_at)}
                    </p>
                  </div>

                  <div className="flex flex-wrap items-center gap-2">
                    {version.is_active ? (
                      <StatusBadge tone="ok">
                        {version.certificate_type
                          ? `Ativa para ${certificateTypeLabel(version.certificate_type)}`
                          : "Ativa (genérica)"}
                      </StatusBadge>
                    ) : (
                      canManage && (
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => {
                            setActivateError("");
                            setActivating(version);
                          }}
                        >
                          Ativar
                        </Button>
                      )
                    )}
                    {canManage && (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          setRenameError("");
                          setRenameName(version.name || `Versão ${version.version_number}`);
                          setRenaming(version);
                        }}
                      >
                        Renomear
                      </Button>
                    )}
                    {canManage && !version.is_active && (
                      <Button
                        size="sm"
                        variant="danger-quiet"
                        icon="trash"
                        onClick={() => {
                          setDeleteError("");
                          setDeleting(version);
                        }}
                      >
                        Excluir
                      </Button>
                    )}
                    {canManage && (
                      <Button
                        size="sm"
                        variant="ghost"
                        icon="duplicate"
                        onClick={() =>
                          openEditor(
                            version.id,
                            `Cópia de v${version.version_number}`,
                            version.certificate_type ?? null,
                          )
                        }
                      >
                        Editar como nova
                      </Button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        {/* Activation — typed confirmation, since it affects every future issue */}
        <ConfirmDialog
          open={Boolean(activating)}
          title={`Ativar versão ${activating?.version_number ?? ""}`}
          description={
            activating?.certificate_type
              ? `Todos os certificados do tipo ${certificateTypeLabel(activating.certificate_type)} emitidos a partir de agora usarão este layout.`
              : "Todos os certificados emitidos a partir de agora usarão este layout, exceto os tipos com versão própria ativa."
          }
          confirmLabel="Ativar esta versão"
          tone="primary"
          busy={activateBusy}
          error={activateError}
          requireTyped="ATIVAR"
          onConfirm={handleActivate}
          onClose={() => {
            if (!activateBusy) {
              setActivating(null);
              setActivateError("");
            }
          }}
        >
          {activating && (
            <div className="flex gap-3">
              <img
                src={bgUrl(activating)}
                alt=""
                className="h-20 w-32 shrink-0 rounded-[var(--radius)] border border-[color:var(--line)] object-contain"
              />
              <div className="min-w-0 text-[length:var(--text-sm)]">
                <p className="text-[color:var(--ink)]">
                  A versão ativa {versionTypeLabel(activating).toLowerCase()} passará de{" "}
                  <strong>
                    {(() => {
                      const current = versions.find(
                        (version) =>
                          version.is_active &&
                          (version.certificate_type ?? null) ===
                            (activating.certificate_type ?? null),
                      );
                      return current ? `v${current.version_number}` : "nenhuma";
                    })()}
                  </strong>{" "}
                  para <strong>v{activating.version_number}</strong>.
                </p>
                <p className="mt-1.5 text-[color:var(--ink-muted)]">
                  Certificados já emitidos não mudam — eles mantêm o layout com
                  que foram gerados.
                </p>
              </div>
            </div>
          )}
        </ConfirmDialog>

        <ConfirmDialog
          open={Boolean(renaming)}
          title={`Renomear versão ${renaming?.version_number ?? ""}`}
          description="O nome é apenas uma identificação administrativa; o layout e os certificados emitidos não serão alterados."
          confirmLabel="Salvar novo nome"
          tone="primary"
          busy={renameBusy}
          error={renameError}
          onConfirm={handleRename}
          onClose={() => {
            if (!renameBusy) {
              setRenaming(null);
              setRenameError("");
            }
          }}
        >
          <Field label="Nome da versão">
            {(props) => (
              <TextInput
                {...props}
                value={renameName}
                maxLength={255}
                autoComplete="off"
                onChange={(event) => setRenameName(event.target.value)}
              />
            )}
          </Field>
        </ConfirmDialog>

        <ConfirmDialog
          open={Boolean(deleting)}
          title={`Excluir versão ${deleting?.version_number ?? ""}`}
          description="Esta ação remove permanentemente esta versão não utilizada."
          confirmLabel="Excluir esta versão"
          busy={deleteBusy}
          error={deleteError}
          requireTyped="EXCLUIR"
          onConfirm={handleDelete}
          onClose={() => {
            if (!deleteBusy) {
              setDeleting(null);
              setDeleteError("");
            }
          }}
        >
          <Alert tone="warn">
            A versão ativa e qualquer versão já usada em certificados não podem ser
            excluídas. Nesses casos, o sistema preserva o histórico automaticamente.
          </Alert>
        </ConfirmDialog>

        {/* Comparison */}
        <AccessibleModal
          open={Boolean(compare)}
          title="Comparar versões"
          description="Escolha duas versões para ver as artes lado a lado."
          size="lg"
          onClose={() => setCompare(null)}
          footer={
            <Button variant="secondary" onClick={() => setCompare(null)}>
              Fechar
            </Button>
          }
        >
          {compare && (
            <div className="grid gap-4 sm:grid-cols-2">
              {[0, 1].map((slot) => (
                <div key={slot}>
                  <label
                    htmlFor={`compare-${slot}`}
                    className="text-[length:var(--text-sm)] font-medium text-[color:var(--ink)]"
                  >
                    {slot === 0 ? "Versão A" : "Versão B"}
                  </label>
                  <select
                    id={`compare-${slot}`}
                    value={compare[slot]?.id ?? ""}
                    onChange={(event) => {
                      const picked = versions.find(
                        (version) => version.id === Number(event.target.value),
                      );
                      if (!picked) return;
                      const next = [...compare];
                      next[slot] = picked;
                      setCompare(next);
                    }}
                    className="mt-1 h-10 w-full rounded-[var(--radius)] border border-[color:var(--line-strong)] bg-[var(--surface)] px-2.5 text-[length:var(--text-sm)]"
                  >
                    {versions.map((version) => (
                      <option key={version.id} value={version.id}>
                        v{version.version_number}
                        {version.name ? ` — ${version.name}` : ""}
                        {version.is_active ? " (ativa)" : ""}
                      </option>
                    ))}
                  </select>

                  {compare[slot] && (
                    <>
                      <img
                        src={bgUrl(compare[slot])}
                        alt={`Arte da versão ${compare[slot].version_number}`}
                        className="mt-2 w-full rounded-[var(--radius)] border border-[color:var(--line)] object-contain"
                      />
                      <dl className="mt-2 space-y-0.5 text-[length:var(--text-xs)] text-[color:var(--ink-muted)]">
                        <div className="flex justify-between gap-2">
                          <dt>Criada em</dt>
                          <dd className="text-[color:var(--ink)]">
                            {formatDate(compare[slot].created_at)}
                          </dd>
                        </div>
                        <div className="flex justify-between gap-2">
                          <dt>Dimensões</dt>
                          <dd className="text-[color:var(--ink)]">
                            {compare[slot].image_width} × {compare[slot].image_height}
                          </dd>
                        </div>
                      </dl>
                    </>
                  )}
                </div>
              ))}
            </div>
          )}
        </AccessibleModal>
      </>
    );
  }

  /* ── Editor view ────────────────────────────────────────────────────── */
  return (
    <>
      {/* Break out of the shell's padded container: the editor wants the whole
          viewport, and a canvas inside a max-width column wastes the screen. */}
      <div className="-mx-3 -my-5 flex h-[calc(100vh-var(--topbar-height))] flex-col sm:-mx-5 sm:-my-6 lg:-mx-8">
        <EditorTopbar
          templateName={templateName}
          certificateType={templateType}
          onCertificateTypeChange={handleCertificateTypeChange}
          saving={saving}
          hasBackground={Boolean(editor.backgroundUrl)}
          isDirty={history.isDirty}
          canUndo={history.canUndo}
          canRedo={history.canRedo}
          showMockData={editor.showMockData}
          showGrid={editor.showGrid}
          zoom={editor.zoom}
          onNameChange={setTemplateName}
          onSave={handleSave}
          onBack={requestBack}
          onUndo={history.undo}
          onRedo={history.redo}
          onRequestClear={() => setClearing(true)}
          onError={(body) => setMessage({ title: "Erro no editor", body })}
          onSetMock={editor.setShowMockData}
          onSetGrid={editor.setShowGrid}
          onSetZoom={editor.setZoom}
          onExport={editor.exportJSON}
          onImport={editorActions.importJSON}
          onBackgroundUploaded={(url, width, height) =>
            editorActions.setBackground(url, width, height)
          }
          onImageUploaded={editorActions.addImageElement}
          onShowShortcuts={() => setShortcutsOpen(true)}
        />

        {saveError && (
          <Alert tone="danger" className="rounded-none border-x-0 border-t-0">
            {saveError}
          </Alert>
        )}
        {editor.canvasError && (
          <Alert
            tone="danger"
            className="rounded-none border-x-0 border-t-0"
            actions={
              <Button size="sm" variant="secondary" onClick={editor.clearCanvasError}>
                Fechar
              </Button>
            }
          >
            {editor.canvasError}
          </Alert>
        )}

        <PerWorkNotice certificateType={templateType} elements={editor.elements} />

        <SettingsNotice
          emptySettings={sample?.empty_settings ?? []}
          canManage={sample?.can_manage_settings ?? false}
          elements={editor.elements}
          fallback={sampleFailed}
        />

        <div className="flex min-h-0 flex-1">
          {isWideEditor ? (
            <>
              <aside className="w-56 shrink-0 border-r border-[color:var(--line)]">
                <ElementList
                  elements={editor.elements}
                  selectedId={editor.selectedId}
                  certificateType={templateType}
                  onAdd={editorActions.addTextElement}
                  onSelect={editor.selectElement}
                  onDelete={editorActions.deleteElement}
                  onDuplicate={editorActions.duplicateElement}
                />
              </aside>

              <EditorCanvas
                canvasRef={editor.canvasRef}
                backgroundUrl={editor.backgroundUrl}
                zoom={editor.zoom}
              />

              <aside className="w-64 shrink-0 border-l border-[color:var(--line)]">
                <PropertiesPanel
                  elements={editor.elements}
                  selectedId={editor.selectedId}
                  certificateType={templateType}
                  onUpdate={editorActions.updateElement}
                  onDelete={editorActions.deleteElement}
                  onDuplicate={editorActions.duplicateElement}
                  textLayouts={editor.textLayouts}
                  layoutSource={editor.layoutSource}
                  imageSize={editor.imageSize}
                />
              </aside>
            </>
          ) : (
            <>
              <EditorCanvas
                canvasRef={editor.canvasRef}
                backgroundUrl={editor.backgroundUrl}
                zoom={editor.zoom}
              />

              {/* One shared side strip on smaller screens. */}
              <aside className="flex w-60 shrink-0 flex-col border-l border-[color:var(--line)] bg-[var(--surface)]">
                <div
                  role="tablist"
                  aria-label="Painéis do editor"
                  className="flex border-b border-[color:var(--line)]"
                >
                  {(["elements", "properties"] as const).map((panel) => (
                    <button
                      key={panel}
                      role="tab"
                      type="button"
                      aria-selected={activeSidePanel === panel}
                      onClick={() => setActiveSidePanel(panel)}
                      className={cn(
                        "flex-1 px-3 py-2 text-[length:var(--text-xs)] font-medium",
                        activeSidePanel === panel
                          ? "border-b-2 border-[color:var(--brand-700)] text-[color:var(--ink)]"
                          : "text-[color:var(--ink-muted)] hover:text-[color:var(--ink)]",
                      )}
                    >
                      {panel === "elements" ? "Elementos" : "Propriedades"}
                    </button>
                  ))}
                </div>
                <div className="min-h-0 flex-1">
                  {activeSidePanel === "elements" ? (
                    <ElementList
                      elements={editor.elements}
                      selectedId={editor.selectedId}
                      certificateType={templateType}
                      onAdd={editorActions.addTextElement}
                      onSelect={editor.selectElement}
                      onDelete={editorActions.deleteElement}
                      onDuplicate={editorActions.duplicateElement}
                    />
                  ) : (
                    <PropertiesPanel
                      elements={editor.elements}
                      selectedId={editor.selectedId}
                      certificateType={templateType}
                      onUpdate={editorActions.updateElement}
                      onDelete={editorActions.deleteElement}
                      onDuplicate={editorActions.duplicateElement}
                      textLayouts={editor.textLayouts}
                      layoutSource={editor.layoutSource}
                      imageSize={editor.imageSize}
                    />
                  )}
                </div>
              </aside>
            </>
          )}
        </div>
      </div>

      {/* Dialogs */}
      <ConfirmDialog
        open={clearing}
        title="Limpar todos os elementos"
        description="A arte de fundo é mantida."
        confirmLabel="Limpar elementos"
        onConfirm={() => {
          editorActions.clearAll();
          setClearing(false);
        }}
        onClose={() => setClearing(false)}
      >
        <p className="text-[length:var(--text-sm)] text-[color:var(--ink)]">
          Todos os campos posicionados no canvas serão removidos. Você ainda pode
          desfazer com Ctrl+Z.
        </p>
      </ConfirmDialog>

      <ConfirmDialog
        open={leaving}
        title="Sair sem salvar?"
        description="As alterações feitas nesta versão serão perdidas."
        confirmLabel="Sair sem salvar"
        onConfirm={() => {
          setLeaving(false);
          history.reset();
          setMode("list");
        }}
        cancelLabel="Continuar editando"
        onClose={() => setLeaving(false)}
      >
        <p className="text-[length:var(--text-sm)] text-[color:var(--ink)]">
          Há alterações que ainda não foram salvas como uma nova versão.
        </p>
      </ConfirmDialog>

      <AccessibleModal
        open={shortcutsOpen}
        title="Atalhos de teclado"
        onClose={() => setShortcutsOpen(false)}
        footer={
          <Button variant="secondary" onClick={() => setShortcutsOpen(false)}>
            Fechar
          </Button>
        }
      >
        <dl className="divide-y divide-[color:var(--line)]">
          {[
            ["Ctrl + Z", "Desfazer"],
            ["Ctrl + Shift + Z", "Refazer"],
            ["Ctrl + S", "Salvar versão"],
            ["Ctrl + +", "Aumentar zoom"],
            ["Ctrl + −", "Diminuir zoom"],
            ["Ctrl + 0", "Zoom 100%"],
            ["Setas", "Mover o elemento selecionado em 1 px"],
            ["Shift + Setas", "Mover o elemento selecionado em 10 px"],
            ["Delete", "Excluir o elemento selecionado"],
            ["?", "Abrir esta lista"],
          ].map(([keys, description]) => (
            <div
              key={keys}
              className="flex items-baseline justify-between gap-4 py-2"
            >
              <dt>
                <kbd className="rounded-[var(--radius-sm)] border border-[color:var(--line-strong)] bg-[var(--surface-sunken)] px-1.5 py-0.5 font-[family-name:var(--font-mono)] text-[length:var(--text-xs)] text-[color:var(--ink)]">
                  {keys}
                </kbd>
              </dt>
              <dd className="text-[length:var(--text-sm)] text-[color:var(--ink-muted)]">
                {description}
              </dd>
            </div>
          ))}
        </dl>
      </AccessibleModal>

      <AccessibleModal
        open={Boolean(message)}
        title={message?.title ?? "Aviso"}
        onClose={() => setMessage(null)}
        footer={
          <Button variant="secondary" onClick={() => setMessage(null)}>
            Fechar
          </Button>
        }
      >
        <p className="text-[length:var(--text-sm)] text-[color:var(--ink)]">
          {message?.body}
        </p>
      </AccessibleModal>

      <span className="sr-only" role="status" aria-live="polite">
        {notice}
      </span>
    </>
  );
}
