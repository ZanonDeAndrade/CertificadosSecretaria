/**
 * Template do certificado — the list of models and the visual editor.
 *
 * Two views in one route. The list is the safe, default view: one item per
 * model (name, type, course, status, certificates issued), filtered by course,
 * type, name and "Mostrar arquivados", the active ones first. The editor is
 * entered deliberately. Key behaviours:
 *
 *  - "Editar" opens the model and "Salvar" updates the same item. The server
 *    keeps a new internal revision when the model already issued certificates
 *    or was ever active; those revisions appear in "Ver histórico".
 *  - Saving the active model changes the next emissions, so it asks for a
 *    typed confirmation ("APLICAR"), like activation ("ATIVAR") does.
 *  - Deleting a model without certificates removes it; with certificates it
 *    is archived (hidden, restorable), and the dialog says which will happen.
 *  - Undo/redo (Ctrl+Z / Ctrl+Shift+Z) via useTemplateHistory; an
 *    unsaved-changes guard on browser exit, on "Voltar" and on every exit
 *    through the navigation drawer.
 *  - The certificate is always shown whole, at the scale that fits the stage;
 *    there is no zoom control.
 *
 * Layout: the editor hides the system sidebar and topbar (the drawer opens
 * from its own menu button), keeps the toolbar to one row and lets both side
 * panels collapse, so the page stays large on a 1366×768 notebook. Below
 * 1280px the two panels share one tabbed strip.
 */
import { useCallback, useEffect, useLayoutEffect, useMemo, useState } from "react";
import EditorCanvas from "../components/editor/EditorCanvas";
import EditorTopbar from "../components/editor/EditorTopbar";
import ElementList from "../components/editor/ElementList";
import ModelDetailsDialog, { ModelDetails } from "../components/editor/ModelDetailsDialog";
import PropertiesPanel from "../components/editor/PropertiesPanel";
import PerWorkNotice from "../components/editor/PerWorkNotice";
import SettingsNotice from "../components/editor/SettingsNotice";
import SidePanel from "../components/editor/SidePanel";
import TemplateHistoryDialog, {
  formatDateTime,
} from "../components/editor/TemplateHistoryDialog";
import { CERTIFICATE_TYPES, certificateTypeLabel, isPerWorkType } from "../domain/certificateTypes";
import { perWorkStartingPoint } from "../domain/perWorkTemplate";
import AccessibleModal from "../components/AccessibleModal";
import ConfirmDialog from "../ui/ConfirmDialog";
import PageHeader from "../ui/PageHeader";
import Panel, { PanelHeader } from "../ui/Panel";
import Alert from "../ui/Alert";
import Button from "../ui/Button";
import StatusBadge from "../ui/StatusBadge";
import { Checkbox, Field, Select, TextInput } from "../ui/Field";
import { EmptyState, ErrorState, Skeleton } from "../ui/Feedback";
import { cn } from "../ui/cn";
import { useEditorCanvas } from "../hooks/useEditorCanvas";
import {
  useTemplateHistory,
  useUnsavedChangesWarning,
} from "../hooks/useTemplateHistory";
import { useAuth } from "../app/AuthContext";
import { useShell } from "../app/ShellContext";
import { useMediaQuery } from "../app/useMediaQuery";
import { failureMessage } from "../app/useAsyncData";
import {
  CertificateTemplate,
  Course,
  GENERIC_TYPE,
  SaveOutcome,
  TemplateVersion,
  activateTemplate,
  createTemplate,
  deleteTemplate,
  duplicateTemplate,
  getTemplate,
  getTemplateHistory,
  getTemplateSampleData,
  listCourses,
  listTemplates,
  restoreTemplate,
  saveTemplate,
  TemplateSampleData,
} from "../services/templateApi";
import { API_BASE_URL } from "../services/api";
import { KEY_LABELS, TemplateElement } from "../types/template";

type EditorMode = "list" | "edit";

/** Course filter: every model, the ones for all courses, or one course. */
type CourseFilter = "" | "none" | number;

/** Shown after "Trocar arte" when the new art has another size than the old one. */
interface ArtNotice {
  previous: { width: number; height: number };
  next: { width: number; height: number };
  /** Labels of the elements whose anchor now lies beyond the page. */
  outside: string[];
}

function artNoticeText({ previous, next, outside }: ArtNotice): string {
  const base =
    `A nova arte tem ${next.width}×${next.height} px; a anterior tinha ` +
    `${previous.width}×${previous.height} px. Os elementos continuam nas mesmas ` +
    "coordenadas em pixels da arte e não foram reposicionados.";
  if (outside.length === 0) return `${base} Confira as posições antes de salvar.`;
  return `${base} Fora da nova página: ${outside.join(", ")}.`;
}

function elementLabel(element: TemplateElement): string {
  return element.label || KEY_LABELS[element.key] || element.key;
}

function bgUrl(template: Pick<CertificateTemplate, "background_url">): string {
  return `${API_BASE_URL.replace(/\/$/, "")}${template.background_url ?? ""}`;
}

/** "Genérico" or the type the model is dedicated to. */
function typeLabel(certificateType: string | null | undefined): string {
  return certificateType ? certificateTypeLabel(certificateType) : "Genérico";
}

function courseLabel(courseName: string | null | undefined): string {
  return courseName || "Todos os cursos";
}

function certificateCountLabel(count: number): string {
  if (count === 0) return "Nenhum certificado";
  return count === 1 ? "1 certificado" : `${count} certificados`;
}

const SAVE_NOTICES: Record<SaveOutcome, string> = {
  unchanged: "Dados do modelo salvos.",
  updated: "Modelo salvo.",
  revised:
    "Modelo salvo. Como ele já gerou certificados ou já esteve ativo, o layout anterior ficou guardado em “Ver histórico”.",
  applied: "Modelo salvo e aplicado: os próximos certificados emitidos usarão este layout.",
};

/** What the editor is working on; null id = a model not created yet. */
interface EditingState {
  id: number | null;
  revision: number | null;
  isActive: boolean;
  typeLocked: boolean;
  original: ModelDetails;
}

/** Pending exit from a dirty editor; `proceed` continues a guarded navigation. */
interface LeaveRequest {
  proceed?: () => void;
}

function isApplyRequired(error: unknown): boolean {
  const response = (error as { response?: { status?: number; data?: { detail?: unknown } } })
    ?.response;
  return (
    response?.status === 409 &&
    typeof response.data?.detail === "string" &&
    /aplicar/i.test(response.data.detail)
  );
}

function isStale(error: unknown): boolean {
  const response = (error as { response?: { status?: number; data?: { detail?: unknown } } })
    ?.response;
  return (
    response?.status === 409 &&
    typeof response.data?.detail === "string" &&
    /outra pessoa/i.test(response.data.detail)
  );
}

export default function TemplateEditor() {
  const { can } = useAuth();
  const canManage = can("templates.manage");
  const { setImmersive, openDrawer, drawerOpen, setLeaveGuard } = useShell();

  const [mode, setMode] = useState<EditorMode>("list");
  const [templates, setTemplates] = useState<CertificateTemplate[]>([]);
  const [courses, setCourses] = useState<Course[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [notice, setNotice] = useState("");

  /* List filters. Course, type and archived go to the server; the name is
   * filtered here, as the operator types. */
  const [query, setQuery] = useState("");
  const [courseFilter, setCourseFilter] = useState<CourseFilter>("");
  const [typeFilter, setTypeFilter] = useState("");
  const [showArchived, setShowArchived] = useState(false);

  /* Editor state. */
  const [editing, setEditing] = useState<EditingState | null>(null);
  const [details, setDetails] = useState<ModelDetails>({
    name: "",
    certificateType: null,
    courseId: null,
  });
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [applyConfirm, setApplyConfirm] = useState(false);
  const [staleConflict, setStaleConflict] = useState(false);
  const [message, setMessage] = useState<{ title: string; body: string } | null>(null);
  const [clearing, setClearing] = useState(false);
  const [leaving, setLeaving] = useState<LeaveRequest | null>(null);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(false);
  const [sample, setSample] = useState<TemplateSampleData | null>(null);
  const [sampleFailed, setSampleFailed] = useState(false);

  /* List dialogs. */
  const [activating, setActivating] = useState<CertificateTemplate | null>(null);
  const [activateBusy, setActivateBusy] = useState(false);
  const [activateError, setActivateError] = useState("");
  const [deleting, setDeleting] = useState<CertificateTemplate | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const [historyFor, setHistoryFor] = useState<CertificateTemplate | null>(null);
  const [history, setHistory] = useState<TemplateVersion[] | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [rowBusy, setRowBusy] = useState<number | null>(null);

  const editor = useEditorCanvas();
  const undoHistory = useTemplateHistory(editor);
  const [artNotice, setArtNotice] = useState<ArtNotice | null>(null);
  const isEditing = mode === "edit";
  const metaDirty = Boolean(
    editing &&
      (details.name !== editing.original.name ||
        details.certificateType !== editing.original.certificateType ||
        details.courseId !== editing.original.courseId),
  );
  const isDirty = undoHistory.isDirty || metaDirty;
  useUnsavedChangesWarning(isEditing && isDirty);

  /* The editor owns the viewport: sidebar and topbar leave with it. A layout
   * effect avoids one frame of the editor inside the padded content column. */
  useLayoutEffect(() => {
    setImmersive(isEditing);
    return () => setImmersive(false);
  }, [isEditing, setImmersive]);

  /* While there are unsaved changes, every exit through the shell (a drawer
   * link, "Sair") goes through the same "Sair sem salvar?" dialog as "Voltar". */
  useEffect(() => {
    if (!isEditing || !isDirty) {
      setLeaveGuard(null);
      return;
    }
    setLeaveGuard((proceed) => setLeaving({ proceed }));
    return () => setLeaveGuard(null);
  }, [isEditing, isDirty, setLeaveGuard]);

  /* Every canvas mutation is routed through `noteUserEdit` so the history layer
   * can tell a real change apart from the layout settling after a load. */
  const { noteUserEdit } = undoHistory;
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
      const [list, courseList] = await Promise.all([
        listTemplates({
          course_id: typeof courseFilter === "number" ? courseFilter : null,
          without_course: courseFilter === "none",
          certificate_type: typeFilter || null,
          include_archived: showArchived,
        }),
        listCourses(),
      ]);
      setTemplates(list);
      setCourses(courseList);
    } catch (error) {
      setLoadError(failureMessage(error, "Não foi possível carregar os modelos."));
    } finally {
      setLoading(false);
    }
  }, [courseFilter, typeFilter, showArchived]);

  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => {
      if (!cancelled && mode === "list") void refreshList();
    });
    return () => {
      cancelled = true;
    };
  }, [mode, refreshList]);

  const visibleTemplates = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return templates;
    return templates.filter((template) => template.name.toLowerCase().includes(needle));
  }, [templates, query]);

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

  const openEditor = async (template: CertificateTemplate | null) => {
    setSaveError("");
    setNotice("");
    setArtNotice(null);
    const initial: ModelDetails = template
      ? {
          name: template.name,
          certificateType: template.certificate_type,
          courseId: template.course_id,
        }
      : { name: "Novo modelo", certificateType: null, courseId: null };
    setDetails(initial);
    setEditing({
      id: template?.id ?? null,
      revision: template?.revision ?? null,
      isActive: Boolean(template?.is_active),
      typeLocked: Boolean(template?.type_locked),
      original: initial,
    });
    setMode("edit");
    undoHistory.reset();
    // Whatever settles on the canvas next is the clean starting point, whether
    // that is an empty canvas or a loaded model.
    undoHistory.markNextAsBaseline();
    void loadSampleData();
    if (!template) {
      editor.clearAll();
      return;
    }
    try {
      const full = await getTemplate(template.id);
      setEditing((current) =>
        current ? { ...current, revision: full.revision, isActive: full.is_active } : current,
      );
      if (full.layout) editor.loadTemplate(full.layout);
    } catch (error) {
      setSaveError(failureMessage(error, "Não foi possível carregar este modelo para edição."));
    }
  };

  /* Choosing a per-work type turns the layout being edited (usually a copy of
   * the generic model) into that type's starting point: no participant name,
   * the body moved up, the authors block above the QR code. It is an
   * ordinary edit, so Ctrl+Z brings the previous layout back. */
  const handleDetailsChange = (next: ModelDetails) => {
    const entering = isPerWorkType(next.certificateType) && !isPerWorkType(details.certificateType);
    setDetails(next);
    if (!entering) return;
    const current = editor.getLayout();
    const start = perWorkStartingPoint(current);
    if (JSON.stringify(start) === JSON.stringify(current)) return;
    noteUserEdit();
    editor.loadTemplate(start);
  };

  /* "Trocar arte" keeps every element at its coordinates in art pixels. When
   * the new art has another size the operator is told so, and which elements
   * now fall beyond the page; nothing is moved for them. */
  const handleBackgroundUploaded = (url: string, width: number, height: number) => {
    const previous = editor.imageSize;
    const replacing = Boolean(editor.backgroundUrl);
    const sameSize = previous.width === width && previous.height === height;
    const layout = editor.getLayout();
    editorActions.setBackground(url, width, height);
    if (!replacing || sameSize) {
      setArtNotice(null);
      return;
    }
    const outside = layout.elements
      .filter((element) => element.x > width || element.y > height)
      .map(elementLabel);
    setArtNotice({ previous, next: { width, height }, outside });
  };

  const finishSave = async (outcome: SaveOutcome | "created") => {
    undoHistory.markSaved();
    setArtNotice(null);
    setApplyConfirm(false);
    setMode("list");
    setNotice(
      outcome === "created"
        ? "Modelo criado. Ele ainda não está ativo — ative-o quando quiser que valha para as próximas emissões."
        : SAVE_NOTICES[outcome],
    );
  };

  const performSave = async (apply: boolean) => {
    if (!editing) return;
    const name = details.name.trim() || "Novo modelo";
    const layout = editor.getLayout();
    if (!layout.background) {
      setSaveError("Envie a arte de fundo antes de salvar o modelo.");
      return;
    }
    setSaving(true);
    setSaveError("");
    try {
      if (editing.id == null) {
        await createTemplate({
          name,
          layout,
          certificate_type: details.certificateType,
          course_id: details.courseId,
        });
        await finishSave("created");
        return;
      }
      const saved = await saveTemplate(editing.id, {
        name,
        ...(editing.typeLocked ? {} : { certificate_type: details.certificateType }),
        course_id: details.courseId,
        // Only a changed layout is sent, so a save of the name alone never
        // touches the revision.
        ...(undoHistory.isDirty ? { layout } : {}),
        revision: editing.revision ?? 1,
        apply,
      });
      await finishSave(saved.outcome);
    } catch (error) {
      if (!apply && isApplyRequired(error)) {
        setApplyConfirm(true);
      } else if (isStale(error)) {
        setStaleConflict(true);
      } else {
        setSaveError(failureMessage(error, "Erro ao salvar o modelo."));
      }
    } finally {
      setSaving(false);
    }
  };

  const handleSave = () => {
    if (!editing) return;
    // The active model: a changed layout reaches the next emissions, so the
    // operator confirms before anything is sent.
    if (editing.id != null && editing.isActive && undoHistory.isDirty) {
      setApplyConfirm(true);
      return;
    }
    void performSave(false);
  };

  const reloadAfterConflict = async () => {
    if (!editing?.id) return;
    setStaleConflict(false);
    const current = templates.find((template) => template.id === editing.id) ?? null;
    try {
      const full = await getTemplate(editing.id);
      await openEditor({ ...(current ?? full), ...full });
    } catch (error) {
      setSaveError(failureMessage(error, "Não foi possível recarregar o modelo."));
    }
  };

  const handleActivate = async () => {
    if (!activating) return;
    setActivateBusy(true);
    setActivateError("");
    try {
      await activateTemplate(activating.id);
      setActivating(null);
      setNotice(`Modelo “${activating.name}” ativado. Os próximos certificados usarão este layout.`);
      await refreshList();
    } catch (error) {
      setActivateError(failureMessage(error, "Não foi possível ativar este modelo."));
    } finally {
      setActivateBusy(false);
    }
  };

  const handleDelete = async () => {
    if (!deleting) return;
    setDeleteBusy(true);
    setDeleteError("");
    try {
      const result = await deleteTemplate(deleting.id);
      setDeleting(null);
      setNotice(
        result.outcome === "archived"
          ? `Modelo “${deleting.name}” arquivado. Os certificados emitidos com ele continuam válidos; use “Mostrar arquivados” para vê-lo ou restaurá-lo.`
          : `Modelo “${deleting.name}” excluído.`,
      );
      await refreshList();
    } catch (error) {
      setDeleteError(failureMessage(error, "Não foi possível excluir este modelo."));
    } finally {
      setDeleteBusy(false);
    }
  };

  const handleRestore = async (template: CertificateTemplate) => {
    setRowBusy(template.id);
    setLoadError("");
    try {
      await restoreTemplate(template.id);
      setNotice(`Modelo “${template.name}” restaurado. Ele volta à lista e continua inativo.`);
      await refreshList();
    } catch (error) {
      setLoadError(failureMessage(error, "Não foi possível restaurar este modelo."));
    } finally {
      setRowBusy(null);
    }
  };

  const handleDuplicate = async (template: CertificateTemplate, version?: TemplateVersion) => {
    setRowBusy(template.id);
    setLoadError("");
    try {
      const copy = await duplicateTemplate(
        template.id,
        version ? { version_id: version.id, name: `${template.name} (revisão ${version.version_number})` } : {},
      );
      setHistoryFor(null);
      setNotice(`Cópia criada como “${copy.name}”. Ela está inativa; edite e ative quando quiser.`);
      await refreshList();
    } catch (error) {
      setLoadError(failureMessage(error, "Não foi possível duplicar este modelo."));
    } finally {
      setRowBusy(null);
    }
  };

  const loadHistory = useCallback(async (template: CertificateTemplate) => {
    setHistoryLoading(true);
    setHistoryError("");
    try {
      setHistory(await getTemplateHistory(template.id));
    } catch (error) {
      setHistory(null);
      setHistoryError(failureMessage(error, "Não foi possível carregar o histórico."));
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  const openHistory = (template: CertificateTemplate) => {
    setHistory(null);
    setHistoryFor(template);
    void loadHistory(template);
  };

  const requestBack = () => {
    if (isDirty) setLeaving({});
    else setMode("list");
  };

  const confirmLeave = () => {
    const pending = leaving?.proceed;
    setLeaving(null);
    undoHistory.reset();
    setMode("list");
    pending?.();
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
        if (event.shiftKey) undoHistory.redo();
        else undoHistory.undo();
        return;
      }
      if (mod && event.key.toLowerCase() === "y") {
        if (typing) return;
        event.preventDefault();
        undoHistory.redo();
        return;
      }
      if (mod && event.key.toLowerCase() === "s") {
        event.preventDefault();
        handleSave();
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
  }, [isEditing, undoHistory, editor.selectedId, editorActions, editing, details]);

  /* ── List view ──────────────────────────────────────────────────────── */
  if (mode === "list") {
    const filtersActive = Boolean(query.trim() || courseFilter !== "" || typeFilter || showArchived);
    const currentActiveFor = (template: CertificateTemplate) =>
      templates.find(
        (candidate) =>
          candidate.is_active &&
          (candidate.certificate_type ?? null) === (template.certificate_type ?? null),
      );

    return (
      <>
        <PageHeader
          title="Template do certificado"
          description="Um modelo por item. O modelo genérico ativo vale para todos os tipos; um tipo pode ter o próprio modelo ativo. O curso só organiza a lista."
          actions={
            canManage ? (
              <Button variant="primary" icon="plus" onClick={() => openEditor(null)}>
                Novo modelo
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
            Seu perfil permite consultar os modelos, mas não criar, editar nem ativar.
          </Alert>
        )}

        <Panel>
          <PanelHeader
            title="Modelos"
            description="Os ativos aparecem primeiro. Excluir um modelo que já gerou certificados apenas o arquiva."
          />

          {/* Filters */}
          <div className="grid gap-3 border-b border-[color:var(--line)] px-4 py-3 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)] sm:px-5">
            <Field label="Buscar por nome" labelHidden>
              {(props) => (
                <TextInput
                  {...props}
                  type="search"
                  placeholder="Buscar por nome"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                />
              )}
            </Field>
            <Field label="Curso" labelHidden>
              {(props) => (
                <Select
                  {...props}
                  value={courseFilter === "" ? "" : String(courseFilter)}
                  onChange={(event) => {
                    const value = event.target.value;
                    setCourseFilter(value === "" ? "" : value === "none" ? "none" : Number(value));
                  }}
                >
                  <option value="">Curso: todos</option>
                  <option value="none">Curso: todos os cursos (sem curso)</option>
                  {courses.map((course) => (
                    <option key={course.id} value={course.id}>
                      Curso: {course.name}
                      {course.is_active ? "" : " (inativo)"}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label="Tipo de certificado" labelHidden>
              {(props) => (
                <Select
                  {...props}
                  value={typeFilter}
                  onChange={(event) => setTypeFilter(event.target.value)}
                >
                  <option value="">Tipo: todos</option>
                  <option value={GENERIC_TYPE}>Tipo: genérico</option>
                  {CERTIFICATE_TYPES.map((option) => (
                    <option key={option.value} value={option.value}>
                      Tipo: {option.label}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <div className="sm:col-span-3">
              <Checkbox
                label="Mostrar arquivados"
                checked={showArchived}
                onChange={(event) => setShowArchived(event.target.checked)}
              />
            </div>
          </div>

          {loading ? (
            <div className="space-y-3 px-4 py-4 sm:px-5">
              {[0, 1, 2].map((row) => (
                <Skeleton key={row} className="h-14" />
              ))}
            </div>
          ) : visibleTemplates.length === 0 ? (
            <EmptyState
              icon="template"
              title={filtersActive ? "Nenhum modelo corresponde aos filtros" : "Nenhum modelo"}
              description={
                filtersActive
                  ? "Limpe a busca ou os filtros para ver os outros modelos."
                  : "Sem um modelo ativo os certificados não podem ser gerados. Crie um modelo e ative-o."
              }
              action={
                canManage && !filtersActive ? (
                  <Button variant="primary" icon="plus" onClick={() => openEditor(null)}>
                    Novo modelo
                  </Button>
                ) : undefined
              }
            />
          ) : (
            <ul className="divide-y divide-[color:var(--line)]">
              {visibleTemplates.map((template) => (
                <li
                  key={template.id}
                  className={cn(
                    "flex flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:px-5",
                    template.is_archived && "bg-[var(--surface-sunken)]",
                  )}
                >
                  <img
                    src={bgUrl(template)}
                    alt=""
                    className="h-14 w-24 shrink-0 rounded-[var(--radius)] border border-[color:var(--line)] object-contain"
                  />
                  <div className="min-w-0 flex-1">
                    <p className="font-medium text-[color:var(--ink)]">{template.name}</p>
                    <p className="mt-0.5 text-[length:var(--text-xs)] text-[color:var(--ink-muted)]">
                      {typeLabel(template.certificate_type)} · {courseLabel(template.course_name)} ·{" "}
                      {certificateCountLabel(template.certificate_count)} · Atualizado em{" "}
                      {formatDateTime(template.updated_at)}
                    </p>
                  </div>

                  <div className="flex flex-wrap items-center gap-2">
                    {template.is_archived ? (
                      <StatusBadge tone="neutral">Arquivado</StatusBadge>
                    ) : template.is_active ? (
                      <StatusBadge tone="ok">
                        {template.certificate_type
                          ? `Ativo para ${certificateTypeLabel(template.certificate_type)}`
                          : "Ativo (genérico)"}
                      </StatusBadge>
                    ) : (
                      canManage && (
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => {
                            setActivateError("");
                            setActivating(template);
                          }}
                        >
                          Ativar
                        </Button>
                      )
                    )}
                    {canManage && !template.is_archived && (
                      <Button size="sm" variant="ghost" onClick={() => openEditor(template)}>
                        Editar
                      </Button>
                    )}
                    {canManage && (
                      <Button
                        size="sm"
                        variant="ghost"
                        icon="duplicate"
                        loading={rowBusy === template.id}
                        onClick={() => handleDuplicate(template)}
                      >
                        Duplicar
                      </Button>
                    )}
                    <Button size="sm" variant="ghost" icon="history" onClick={() => openHistory(template)}>
                      Ver histórico
                    </Button>
                    {canManage && template.is_archived && (
                      <Button
                        size="sm"
                        variant="secondary"
                        icon="refresh"
                        loading={rowBusy === template.id}
                        onClick={() => handleRestore(template)}
                      >
                        Restaurar
                      </Button>
                    )}
                    {canManage && !template.is_active && !template.is_archived && (
                      <Button
                        size="sm"
                        variant="danger-quiet"
                        icon="trash"
                        onClick={() => {
                          setDeleteError("");
                          setDeleting(template);
                        }}
                      >
                        Excluir
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
          title={`Ativar modelo “${activating?.name ?? ""}”`}
          description={
            activating?.certificate_type
              ? `Todos os certificados do tipo ${certificateTypeLabel(activating.certificate_type)} emitidos a partir de agora usarão este layout.`
              : "Todos os certificados emitidos a partir de agora usarão este layout, exceto os tipos com modelo próprio ativo."
          }
          confirmLabel="Ativar este modelo"
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
                  O modelo ativo {typeLabel(activating.certificate_type).toLowerCase()} passará de{" "}
                  <strong>{currentActiveFor(activating)?.name ?? "nenhum"}</strong> para{" "}
                  <strong>{activating.name}</strong>.
                </p>
                <p className="mt-1.5 text-[color:var(--ink-muted)]">
                  Certificados já emitidos não mudam — eles mantêm o layout com que foram
                  gerados.
                </p>
              </div>
            </div>
          )}
        </ConfirmDialog>

        {/* Delete or archive: the dialog says which, from the certificate count. */}
        <ConfirmDialog
          open={Boolean(deleting)}
          title={
            deleting && deleting.reference_count > 0
              ? `Arquivar modelo “${deleting.name}”`
              : `Excluir modelo “${deleting?.name ?? ""}”`
          }
          description={
            deleting && deleting.reference_count > 0
              ? `Este modelo já gerou ${certificateCountLabel(deleting.certificate_count).toLowerCase()}, por isso não será apagado: ele sai da lista e dos seletores, mas o registro fica guardado e os certificados, a validação pública e a reemissão continuam funcionando.`
              : "Este modelo nunca gerou certificados e será apagado de verdade, com todas as suas revisões."
          }
          confirmLabel={
            deleting && deleting.reference_count > 0 ? "Arquivar este modelo" : "Excluir este modelo"
          }
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
          {deleting && deleting.reference_count > 0 && (
            <Alert tone="info" live={false}>
              Para ver ou restaurar um modelo arquivado, marque “Mostrar arquivados” na lista.
            </Alert>
          )}
        </ConfirmDialog>

        <TemplateHistoryDialog
          template={historyFor}
          versions={history}
          loading={historyLoading}
          error={historyError}
          canManage={canManage}
          onDuplicate={(version) => historyFor && handleDuplicate(historyFor, version)}
          onRetry={() => historyFor && loadHistory(historyFor)}
          onClose={() => setHistoryFor(null)}
        />
      </>
    );
  }

  /* ── Editor view ────────────────────────────────────────────────────── */
  const reportError = (body: string) => setMessage({ title: "Erro no editor", body });
  const elementList = (
    <ElementList
      elements={editor.elements}
      selectedId={editor.selectedId}
      certificateType={details.certificateType}
      onAdd={editorActions.addTextElement}
      onAddImage={editorActions.addImageElement}
      onError={reportError}
      onSelect={editor.selectElement}
      onDelete={editorActions.deleteElement}
      onDuplicate={editorActions.duplicateElement}
    />
  );
  const propertiesPanel = (
    <PropertiesPanel
      elements={editor.elements}
      selectedId={editor.selectedId}
      certificateType={details.certificateType}
      onUpdate={editorActions.updateElement}
      onDelete={editorActions.deleteElement}
      onDuplicate={editorActions.duplicateElement}
      textLayouts={editor.textLayouts}
      layoutSource={editor.layoutSource}
      imageSize={editor.imageSize}
    />
  );
  const currentCourse = courses.find((course) => course.id === details.courseId);

  return (
    <>
      {/* The shell is immersive here: no sidebar, no topbar, no padding. The
          editor is the viewport, and the stage fits the whole page into
          whatever is left after the toolbar, the notices and the panels. */}
      <div className="flex h-[100dvh] flex-col">
        <EditorTopbar
          templateName={details.name}
          typeLabel={typeLabel(details.certificateType)}
          courseLabel={courseLabel(currentCourse?.name)}
          onOpenModelDetails={() => setDetailsOpen(true)}
          saving={saving}
          hasBackground={Boolean(editor.backgroundUrl)}
          isDirty={isDirty}
          canUndo={undoHistory.canUndo}
          canRedo={undoHistory.canRedo}
          showMockData={editor.showMockData}
          showGrid={editor.showGrid}
          menuOpen={drawerOpen}
          onOpenMenu={openDrawer}
          onSave={handleSave}
          onBack={requestBack}
          onUndo={undoHistory.undo}
          onRedo={undoHistory.redo}
          onRequestClear={() => setClearing(true)}
          onError={reportError}
          onSetMock={editor.setShowMockData}
          onSetGrid={editor.setShowGrid}
          onExport={editor.exportJSON}
          onImport={editorActions.importJSON}
          onBackgroundUploaded={handleBackgroundUploaded}
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
        {artNotice && (
          <Alert
            tone="info"
            className="rounded-none border-x-0 border-t-0"
            actions={
              <Button size="sm" variant="secondary" onClick={() => setArtNotice(null)}>
                Fechar
              </Button>
            }
          >
            {artNoticeText(artNotice)}
          </Alert>
        )}

        <PerWorkNotice certificateType={details.certificateType} elements={editor.elements} />

        <SettingsNotice
          emptySettings={sample?.empty_settings ?? []}
          canManage={sample?.can_manage_settings ?? false}
          elements={editor.elements}
          fallback={sampleFailed}
        />

        <div className="flex min-h-0 flex-1">
          {isWideEditor ? (
            <>
              <SidePanel
                title="Elementos"
                side="left"
                widthClass="w-56"
                collapsed={leftCollapsed}
                onToggle={() => setLeftCollapsed((value) => !value)}
              >
                {elementList}
              </SidePanel>

              <EditorCanvas
                canvasRef={editor.canvasRef}
                stageRef={editor.stageRef}
                backgroundUrl={editor.backgroundUrl}
              />

              <SidePanel
                title="Propriedades"
                side="right"
                widthClass="w-60"
                collapsed={rightCollapsed}
                onToggle={() => setRightCollapsed((value) => !value)}
              >
                {propertiesPanel}
              </SidePanel>
            </>
          ) : (
            <>
              <EditorCanvas
                canvasRef={editor.canvasRef}
                stageRef={editor.stageRef}
                backgroundUrl={editor.backgroundUrl}
              />

              {/* One shared side strip on smaller screens. */}
              <SidePanel
                title="Painéis"
                side="right"
                widthClass="w-60"
                collapsed={rightCollapsed}
                onToggle={() => setRightCollapsed((value) => !value)}
              >
                <div className="flex h-full flex-col bg-[var(--surface)]">
                  <div
                    role="tablist"
                    aria-label="Painéis do editor"
                    className="flex border-b border-[color:var(--line)] pr-9"
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
                    {activeSidePanel === "elements" ? elementList : propertiesPanel}
                  </div>
                </div>
              </SidePanel>
            </>
          )}
        </div>
      </div>

      {/* Dialogs */}
      <ModelDetailsDialog
        open={detailsOpen}
        details={details}
        courses={courses}
        typeLocked={Boolean(editing?.typeLocked)}
        onChange={handleDetailsChange}
        onClose={() => setDetailsOpen(false)}
      />

      <ConfirmDialog
        open={applyConfirm}
        title="Salvar e aplicar às próximas emissões?"
        description={
          details.certificateType
            ? `Este modelo está ativo para ${certificateTypeLabel(details.certificateType)}: ao salvar, todos os certificados desse tipo emitidos a partir de agora usarão o novo layout, inclusive lotes que já estão na fila.`
            : "Este é o modelo genérico ativo: ao salvar, todos os certificados emitidos a partir de agora usarão o novo layout (exceto os tipos com modelo próprio ativo), inclusive lotes que já estão na fila."
        }
        confirmLabel="Salvar e aplicar às próximas emissões"
        tone="primary"
        busy={saving}
        error={saveError}
        requireTyped="APLICAR"
        onConfirm={() => void performSave(true)}
        onClose={() => {
          if (!saving) setApplyConfirm(false);
        }}
      >
        <p className="text-[length:var(--text-sm)] text-[color:var(--ink)]">
          O layout atual fica guardado em “Ver histórico”, e os certificados já emitidos
          não mudam.
        </p>
      </ConfirmDialog>

      <AccessibleModal
        open={staleConflict}
        title="Este modelo foi alterado por outra pessoa"
        description="Desde que você o abriu, o modelo foi salvo em outra sessão. Para não sobrescrever esse trabalho, recarregue o modelo e refaça as suas alterações."
        onClose={() => setStaleConflict(false)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setStaleConflict(false)}>
              Continuar editando
            </Button>
            <Button variant="primary" icon="refresh" onClick={() => void reloadAfterConflict()}>
              Recarregar o modelo
            </Button>
          </>
        }
      >
        <p className="text-[length:var(--text-sm)] text-[color:var(--ink)]">
          Se preferir guardar o que fez, use “Mais → Exportar JSON” antes de recarregar.
        </p>
      </AccessibleModal>

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
        open={Boolean(leaving)}
        title="Sair sem salvar?"
        description="As alterações feitas neste modelo serão perdidas."
        confirmLabel="Sair sem salvar"
        onConfirm={confirmLeave}
        cancelLabel="Continuar editando"
        onClose={() => setLeaving(null)}
      >
        <p className="text-[length:var(--text-sm)] text-[color:var(--ink)]">
          Há alterações que ainda não foram salvas.
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
            ["Ctrl + S", "Salvar"],
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
