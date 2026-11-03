import { FormEvent, useEffect, useState } from "react";
import { useAuth } from "../app/AuthContext";
import { useInstitution } from "../app/InstitutionContext";
import { failureMessage, useAsyncData } from "../app/useAsyncData";
import {
  getInstitutionalSettings,
  InstitutionalSettingsInput,
  updateInstitutionalSettings,
} from "../services/api";
import { Course, createCourse, listCourses, updateCourse } from "../services/templateApi";
import Alert from "../ui/Alert";
import Button from "../ui/Button";
import ConfirmDialog from "../ui/ConfirmDialog";
import { Checkbox, Field, TextInput } from "../ui/Field";
import { ErrorState, Skeleton } from "../ui/Feedback";
import PageHeader from "../ui/PageHeader";
import Panel, { PanelBody, PanelHeader, PanelSection } from "../ui/Panel";
import StatusBadge from "../ui/StatusBadge";
import { cn } from "../ui/cn";

const EMPTY: InstitutionalSettingsInput = {
  institution_name: "",
  issue_location: "",
  signatory_name: "",
  signatory_title: "",
  public_url: "",
  retention_days: 0,
  max_batch_rows: 500,
  max_upload_mb: 10,
  secretaria_can_revoke: true,
  secretaria_can_reissue: true,
};

export default function Configuracoes() {
  const { can } = useAuth();
  const institution = useInstitution();
  const state = useAsyncData(getInstitutionalSettings, []);
  const [draft, setDraft] = useState(EMPTY);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!state.data) return;
    const { id: _id, updated_at: _updatedAt, updated_by: _updatedBy, ...input } =
      state.data;
    setDraft(input);
  }, [state.data]);

  const setNumber = (
    key: "retention_days" | "max_batch_rows" | "max_upload_mb",
    value: string,
  ) => setDraft((current) => ({ ...current, [key]: Number(value) || 0 }));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!can("settings.manage") || saving) return;
    setSaving(true);
    setNotice("");
    setError("");
    try {
      const saved = await updateInstitutionalSettings(draft);
      const { id: _id, updated_at: _updatedAt, updated_by: _updatedBy, ...input } =
        saved;
      setDraft(input);
      setNotice("Configurações institucionais atualizadas e registradas na auditoria.");
      await institution.refresh();
      state.reload();
    } catch (requestError) {
      setError(
        failureMessage(requestError, "Não foi possível salvar as configurações."),
      );
    } finally {
      setSaving(false);
    }
  };

  if (state.initialLoading) {
    return (
      <Panel aria-busy="true" aria-label="Carregando configurações">
        <PanelBody className="space-y-3">
          <Skeleton width="45%" />
          <Skeleton />
          <Skeleton />
        </PanelBody>
      </Panel>
    );
  }

  return (
    <>
      <PageHeader
        title="Configurações institucionais"
        description="Dados de negócio usados na emissão e limites operacionais."
      />

      {state.failure && (
        <Panel>
          <ErrorState
            offline={state.failure === "offline"}
            description={state.error}
            onRetry={state.reload}
          />
        </Panel>
      )}

      {!state.failure && (
        <form onSubmit={submit} className="space-y-4">
          {notice && <Alert tone="ok">{notice}</Alert>}
          {error && <Alert tone="danger">{error}</Alert>}
          {!can("settings.manage") && (
            <Alert tone="info">Esta configuração está disponível somente para leitura.</Alert>
          )}

          <Panel>
            <PanelHeader
              title="Identidade e emissão"
              description="Estes valores substituem textos institucionais fixos no sistema e no certificado."
            />
            <PanelBody className="grid gap-4 sm:grid-cols-2">
              <Field label="Nome da instituição" required>
                {(props) => (
                  <TextInput
                    {...props}
                    value={draft.institution_name}
                    disabled={!can("settings.manage") || saving}
                    onChange={(event) =>
                      setDraft({ ...draft, institution_name: event.target.value })
                    }
                  />
                )}
              </Field>
              <Field
                label="Cidade (local de emissão)"
                hint="Sai como “Cidade, data.” nos certificados. Vazio deixa só a data."
              >
                {(props) => (
                  <TextInput
                    {...props}
                    value={draft.issue_location}
                    disabled={!can("settings.manage") || saving}
                    onChange={(event) =>
                      setDraft({ ...draft, issue_location: event.target.value })
                    }
                  />
                )}
              </Field>
              <Field label="Assinante">
                {(props) => (
                  <TextInput
                    {...props}
                    value={draft.signatory_name}
                    disabled={!can("settings.manage") || saving}
                    onChange={(event) =>
                      setDraft({ ...draft, signatory_name: event.target.value })
                    }
                  />
                )}
              </Field>
              <Field label="Cargo do assinante">
                {(props) => (
                  <TextInput
                    {...props}
                    value={draft.signatory_title}
                    disabled={!can("settings.manage") || saving}
                    onChange={(event) =>
                      setDraft({ ...draft, signatory_title: event.target.value })
                    }
                  />
                )}
              </Field>
              <Field
                label="URL pública"
                hint="Base HTTPS usada no QR Code e na validação pública."
                className="sm:col-span-2"
              >
                {(props) => (
                  <TextInput
                    {...props}
                    type="url"
                    value={draft.public_url}
                    placeholder="https://certificados.exemplo.br"
                    disabled={!can("settings.manage") || saving}
                    onChange={(event) =>
                      setDraft({ ...draft, public_url: event.target.value })
                    }
                  />
                )}
              </Field>
            </PanelBody>

            <PanelSection className="grid gap-4 sm:grid-cols-3">
              <Field label="Retenção (dias)" hint="0 mantém por prazo indeterminado.">
                {(props) => (
                  <TextInput
                    {...props}
                    type="number"
                    min={0}
                    max={36500}
                    value={draft.retention_days}
                    disabled={!can("settings.manage") || saving}
                    onChange={(event) => setNumber("retention_days", event.target.value)}
                  />
                )}
              </Field>
              <Field label="Linhas por lote">
                {(props) => (
                  <TextInput
                    {...props}
                    type="number"
                    min={1}
                    max={10000}
                    value={draft.max_batch_rows}
                    disabled={!can("settings.manage") || saving}
                    onChange={(event) => setNumber("max_batch_rows", event.target.value)}
                  />
                )}
              </Field>
              <Field label="Upload máximo (MB)">
                {(props) => (
                  <TextInput
                    {...props}
                    type="number"
                    min={1}
                    max={100}
                    value={draft.max_upload_mb}
                    disabled={!can("settings.manage") || saving}
                    onChange={(event) => setNumber("max_upload_mb", event.target.value)}
                  />
                )}
              </Field>
            </PanelSection>

            <PanelSection>
              <h3 className="mb-2 text-[length:var(--text-sm)] font-semibold text-[color:var(--ink)]">
                Regra institucional da secretaria
              </h3>
              <div className="flex flex-col gap-1 sm:flex-row sm:gap-6">
                <Checkbox
                  label="Pode revogar certificados"
                  checked={draft.secretaria_can_revoke}
                  disabled={!can("settings.manage") || saving}
                  onChange={(event) =>
                    setDraft({ ...draft, secretaria_can_revoke: event.target.checked })
                  }
                />
                <Checkbox
                  label="Pode reemitir certificados"
                  checked={draft.secretaria_can_reissue}
                  disabled={!can("settings.manage") || saving}
                  onChange={(event) =>
                    setDraft({ ...draft, secretaria_can_reissue: event.target.checked })
                  }
                />
              </div>
            </PanelSection>
          </Panel>

          <Alert tone="info" live={false}>
            Segredos, credenciais, tokens e chaves não pertencem a esta área e continuam
            exclusivamente nas variáveis seguras do ambiente.
          </Alert>

          {can("settings.manage") && (
            <Button
              type="submit"
              variant="primary"
              icon="save"
              loading={saving}
              disabled={!draft.institution_name.trim() || draft.max_batch_rows < 1}
            >
              Salvar configurações
            </Button>
          )}
        </form>
      )}

      <CoursesPanel canManage={can("settings.manage")} />
    </>
  );
}

/**
 * Registered courses. Templates are filed under one of them, so the same
 * spelling is used everywhere. A course is deactivated, never deleted: a
 * template may still point at it. The spreadsheet keeps its own fixed list.
 */
function CoursesPanel({ canManage }: { canManage: boolean }) {
  const state = useAsyncData(() => listCourses(true), []);
  const [newName, setNewName] = useState("");
  const [busy, setBusy] = useState<number | "new" | null>(null);
  const [renaming, setRenaming] = useState<Course | null>(null);
  const [renameName, setRenameName] = useState("");
  const [renameError, setRenameError] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const add = async (event: FormEvent) => {
    event.preventDefault();
    if (!newName.trim() || busy) return;
    setBusy("new");
    setError("");
    setNotice("");
    try {
      const created = await createCourse(newName.trim());
      setNewName("");
      setNotice(`Curso “${created.name}” cadastrado.`);
      state.reload();
    } catch (requestError) {
      setError(failureMessage(requestError, "Não foi possível cadastrar o curso."));
    } finally {
      setBusy(null);
    }
  };

  const toggle = async (course: Course) => {
    setBusy(course.id);
    setError("");
    setNotice("");
    try {
      await updateCourse(course.id, { is_active: !course.is_active });
      setNotice(
        course.is_active
          ? `Curso “${course.name}” desativado. Ele deixa de aparecer ao escolher o curso de um modelo.`
          : `Curso “${course.name}” reativado.`,
      );
      state.reload();
    } catch (requestError) {
      setError(failureMessage(requestError, "Não foi possível alterar o curso."));
    } finally {
      setBusy(null);
    }
  };

  const rename = async () => {
    if (!renaming) return;
    const clean = renameName.trim();
    if (!clean) {
      setRenameError("Informe o nome do curso.");
      return;
    }
    setBusy(renaming.id);
    setRenameError("");
    try {
      await updateCourse(renaming.id, { name: clean });
      setRenaming(null);
      setNotice(`Curso renomeado para “${clean}”.`);
      state.reload();
    } catch (requestError) {
      setRenameError(failureMessage(requestError, "Não foi possível renomear o curso."));
    } finally {
      setBusy(null);
    }
  };

  return (
    <Panel className="mt-6">
      <PanelHeader
        title="Cursos"
        description="Lista usada para classificar os modelos de certificado. O curso de um modelo só organiza a lista de modelos; a emissão escolhe o modelo pelo tipo de certificado."
      />
      <PanelBody className="space-y-4">
        {notice && <Alert tone="ok">{notice}</Alert>}
        {error && <Alert tone="danger">{error}</Alert>}
        {state.failure && (
          <ErrorState
            offline={state.failure === "offline"}
            description={state.error}
            onRetry={state.reload}
          />
        )}
        {state.initialLoading && <Skeleton className="h-24" />}
        {state.data && (
          <ul className="divide-y divide-[color:var(--line)] rounded-[var(--radius)] border border-[color:var(--line)]">
            {state.data.map((course) => (
              <li key={course.id} className="flex flex-wrap items-center gap-2 px-3 py-2">
                <span
                  className={cn(
                    "min-w-0 flex-1 text-[length:var(--text-sm)]",
                    course.is_active
                      ? "text-[color:var(--ink)]"
                      : "text-[color:var(--ink-muted)] line-through",
                  )}
                >
                  {course.name}
                </span>
                {!course.is_active && <StatusBadge tone="neutral">Inativo</StatusBadge>}
                {canManage && (
                  <>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        setRenameError("");
                        setRenameName(course.name);
                        setRenaming(course);
                      }}
                    >
                      Renomear
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      loading={busy === course.id}
                      onClick={() => toggle(course)}
                    >
                      {course.is_active ? "Desativar" : "Reativar"}
                    </Button>
                  </>
                )}
              </li>
            ))}
          </ul>
        )}
        {canManage && (
          <form onSubmit={add} className="flex flex-col gap-2 sm:flex-row sm:items-end">
            <Field label="Novo curso" className="flex-1">
              {(props) => (
                <TextInput
                  {...props}
                  value={newName}
                  maxLength={255}
                  autoComplete="off"
                  placeholder="Nome do curso"
                  onChange={(event) => setNewName(event.target.value)}
                />
              )}
            </Field>
            <Button
              type="submit"
              variant="secondary"
              icon="plus"
              loading={busy === "new"}
              disabled={!newName.trim()}
            >
              Adicionar curso
            </Button>
          </form>
        )}
      </PanelBody>

      <ConfirmDialog
        open={Boolean(renaming)}
        title={`Renomear curso “${renaming?.name ?? ""}”`}
        description="Os modelos classificados neste curso passam a mostrar o novo nome. A leitura da planilha não muda."
        confirmLabel="Salvar novo nome"
        tone="primary"
        busy={busy === renaming?.id}
        error={renameError}
        onConfirm={rename}
        onClose={() => {
          if (busy === null) {
            setRenaming(null);
            setRenameError("");
          }
        }}
      >
        <Field label="Nome do curso">
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
    </Panel>
  );
}
