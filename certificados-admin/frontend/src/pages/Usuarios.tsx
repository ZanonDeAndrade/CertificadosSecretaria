import { FormEvent, useEffect, useRef, useState } from "react";
import { useAuth } from "../app/AuthContext";
import { failureMessage, useAsyncData } from "../app/useAsyncData";
import { ROLE_DESCRIPTIONS, ROLE_LABELS, Role } from "../app/permissions";
import AccessibleModal from "../components/AccessibleModal";
import {
  AdminUserRow,
  createAdminUser,
  listAdminUsers,
  resetAdminUserPassword,
  revokeAdminUserSessions,
  setAdminUserActive,
  updateAdminUser,
} from "../services/api";
import {
  MIN_PASSWORD_LENGTH,
  PASSWORD_POLICY_HINT,
  passwordPolicyError,
} from "../security/passwordPolicy";
import Alert from "../ui/Alert";
import Button from "../ui/Button";
import ConfirmDialog from "../ui/ConfirmDialog";
import { Field, Select, TextInput } from "../ui/Field";
import { EmptyState, ErrorState, TableSkeleton } from "../ui/Feedback";
import PageHeader from "../ui/PageHeader";
import Panel, { PanelHeader } from "../ui/Panel";
import StatusBadge from "../ui/StatusBadge";
import { Table, TableScroll, Tbody, Td, TdHeader, Th, Thead, Tr } from "../ui/Table";

interface UserFormState {
  name: string;
  username: string;
  role: Role;
  temporaryPassword: string;
}

type Confirmation =
  | { kind: "active"; user: AdminUserRow; active: boolean }
  | { kind: "sessions"; user: AdminUserRow };

const EMPTY_FORM: UserFormState = {
  name: "",
  username: "",
  role: "secretaria",
  temporaryPassword: "",
};

function formatDate(value?: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? "—"
    : parsed.toLocaleDateString("pt-BR", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
      });
}

export default function Usuarios() {
  const { user: currentUser } = useAuth();
  const state = useAsyncData(() => listAdminUsers(), []);
  const [editor, setEditor] = useState<"create" | AdminUserRow | null>(null);
  const [form, setForm] = useState<UserFormState>(EMPTY_FORM);
  const [resetTarget, setResetTarget] = useState<AdminUserRow | null>(null);
  const [resetPassword, setResetPassword] = useState("");
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [busy, setBusy] = useState(false);
  const [dialogError, setDialogError] = useState("");
  const [notice, setNotice] = useState("");
  const firstInputRef = useRef<HTMLInputElement>(null);

  const users = state.data?.items ?? [];

  useEffect(() => {
    if (editor === "create") setForm(EMPTY_FORM);
    else if (editor) {
      setForm({
        name: editor.name,
        username: editor.username,
        role: editor.role as Role,
        temporaryPassword: "",
      });
    }
    setDialogError("");
  }, [editor]);

  const closeEditor = () => {
    if (!busy) setEditor(null);
  };

  const saveUser = async (event: FormEvent) => {
    event.preventDefault();
    if (!editor || busy) return;
    const name = form.name.trim();
    const username = form.username.trim();
    if (name.length < 2 || !username) return;
    if (editor === "create") {
      const passwordError = passwordPolicyError(form.temporaryPassword);
      if (passwordError) {
        setDialogError(passwordError);
        return;
      }
    }
    setBusy(true);
    setDialogError("");
    try {
      if (editor === "create") {
        await createAdminUser({
          name,
          username,
          role: form.role,
          temporary_password: form.temporaryPassword,
        });
        setNotice(
          `Usuário ${username} criado. Ele deverá trocar a senha temporária no primeiro acesso.`,
        );
      } else {
        const result = await updateAdminUser(editor.id, {
          name,
          username,
          role: form.role,
        });
        setNotice(
          `Dados de ${result.user.username} atualizados.${
            result.sessions_revoked
              ? ` ${result.sessions_revoked} sessão(ões) encerrada(s).`
              : ""
          }`,
        );
      }
      setEditor(null);
      await state.reload();
    } catch (requestError) {
      setDialogError(
        failureMessage(requestError, "Não foi possível salvar o usuário."),
      );
    } finally {
      setBusy(false);
    }
  };

  const confirmAction = async () => {
    if (!confirmation || busy) return;
    setBusy(true);
    setDialogError("");
    try {
      if (confirmation.kind === "active") {
        const result = await setAdminUserActive(
          confirmation.user.id,
          confirmation.active,
        );
        setNotice(
          confirmation.active
            ? `Acesso de ${result.user.username} reativado.`
            : `Acesso de ${result.user.username} inativado e ${result.sessions_revoked} sessão(ões) encerrada(s).`,
        );
      } else {
        const count = await revokeAdminUserSessions(confirmation.user.id);
        setNotice(
          `${count} sessão(ões) de ${confirmation.user.username} foram encerradas.`,
        );
      }
      setConfirmation(null);
      await state.reload();
    } catch (requestError) {
      setDialogError(
        failureMessage(requestError, "Não foi possível concluir a operação."),
      );
    } finally {
      setBusy(false);
    }
  };

  const submitReset = async (event: FormEvent) => {
    event.preventDefault();
    if (!resetTarget || passwordPolicyError(resetPassword) || busy) return;
    setBusy(true);
    setDialogError("");
    try {
      const result = await resetAdminUserPassword(resetTarget.id, resetPassword);
      setNotice(
        `Senha de ${result.user.username} redefinida. ${result.sessions_revoked} sessão(ões) encerrada(s); a troca será exigida no próximo acesso.`,
      );
      setResetTarget(null);
      setResetPassword("");
      await state.reload();
    } catch (requestError) {
      setDialogError(
        failureMessage(requestError, "Não foi possível redefinir a senha."),
      );
    } finally {
      setBusy(false);
    }
  };

  const confirmationText = confirmation
    ? confirmation.kind === "sessions"
      ? {
          title: "Revogar todas as sessões",
          description: "Os acessos abertos serão encerrados imediatamente.",
          label: "Revogar sessões",
          tone: "danger" as const,
          body: `Revogar todas as sessões de ${confirmation.user.name} (${confirmation.user.username})?`,
        }
      : {
          title: confirmation.active ? "Reativar usuário" : "Inativar usuário",
          description: confirmation.active
            ? "O usuário poderá entrar novamente."
            : "O usuário perderá o acesso e suas sessões serão revogadas.",
          label: confirmation.active ? "Reativar usuário" : "Inativar usuário",
          tone: confirmation.active ? ("primary" as const) : ("danger" as const),
          body: `${confirmation.active ? "Reativar" : "Inativar"} ${confirmation.user.name} (${confirmation.user.username})?`,
        }
    : null;

  return (
    <>
      <PageHeader
        title="Usuários"
        description="Criação, perfis, senhas temporárias e controle de sessões."
        actions={
          <Button variant="primary" icon="plus" onClick={() => setEditor("create")}>
            Criar usuário
          </Button>
        }
      />

      {notice && (
        <Alert tone="ok" className="mb-4">
          {notice}
        </Alert>
      )}

      <Alert tone="info" live={false} className="mb-4">
        Senhas temporárias nunca são exibidas pelo servidor nem permanecem nesta
        tela. Entregue-as por um canal institucional separado; a troca é obrigatória
        no primeiro acesso.
      </Alert>

      <Panel>
        <PanelHeader
          title="Contas cadastradas"
          description={`${state.data?.total ?? 0} conta(s). Alterações de perfil e estado são auditadas.`}
          actions={
            <Button variant="secondary" size="sm" icon="refresh" onClick={state.reload}>
              Atualizar
            </Button>
          }
        />

        {state.failure ? (
          <ErrorState
            offline={state.failure === "offline"}
            description={state.error}
            onRetry={state.reload}
          />
        ) : (
          <TableScroll label="Usuários do sistema" className="rounded-none border-0 border-t">
            <Table caption="Usuários, perfis, estado e ações administrativas">
              <Thead>
                <Tr>
                  <Th>Nome e login</Th>
                  <Th>Perfil</Th>
                  <Th>Situação</Th>
                  <Th className="hidden lg:table-cell">Segurança</Th>
                  <Th className="hidden xl:table-cell">Criado em</Th>
                  <Th><span className="sr-only">Ações</span></Th>
                </Tr>
              </Thead>
              <Tbody>
                {state.initialLoading ? (
                  <TableSkeleton rows={4} columns={6} />
                ) : users.length === 0 ? (
                  <tr>
                    <td colSpan={6}>
                      <EmptyState
                        icon="users"
                        title="Nenhum usuário cadastrado"
                        description="Crie uma conta para iniciar a gestão de acessos."
                        action={
                          <Button variant="primary" icon="plus" onClick={() => setEditor("create")}>
                            Criar usuário
                          </Button>
                        }
                      />
                    </td>
                  </tr>
                ) : (
                  users.map((row) => {
                    const isSelf = row.id === currentUser?.id;
                    return (
                      <Tr key={row.id}>
                        <TdHeader>
                          <span className="block">{row.name}</span>
                          <span className="block text-[length:var(--text-xs)] font-normal text-[color:var(--ink-muted)]">
                            {row.username}{isSelf ? " · você" : ""}
                          </span>
                        </TdHeader>
                        <Td>{ROLE_LABELS[row.role as Role] ?? row.role}</Td>
                        <Td>
                          <StatusBadge
                            tone={row.is_active ? "ok" : "neutral"}
                            icon={row.is_active ? "success" : "lock"}
                          >
                            {row.is_active ? "Ativo" : "Inativo"}
                          </StatusBadge>
                        </Td>
                        <Td className="hidden lg:table-cell">
                          {row.must_change_password ? (
                            <StatusBadge tone="warn" icon="clock">Troca pendente</StatusBadge>
                          ) : (
                            <span className="text-[color:var(--ink-muted)]">Senha permanente</span>
                          )}
                        </Td>
                        <Td className="hidden whitespace-nowrap text-[color:var(--ink-muted)] xl:table-cell">
                          {formatDate(row.created_at)}
                        </Td>
                        <Td>
                          <div className="flex flex-wrap justify-end gap-1">
                            <Button size="sm" onClick={() => setEditor(row)}>Editar</Button>
                            <Button
                              size="sm"
                              disabled={isSelf}
                              title={
                                isSelf
                                  ? "Altere sua própria senha em Meu perfil, informando a senha atual."
                                  : undefined
                              }
                              onClick={() => setResetTarget(row)}
                            >
                              Redefinir senha
                            </Button>
                            <Button
                              size="sm"
                              onClick={() => setConfirmation({ kind: "sessions", user: row })}
                            >
                              Revogar sessões
                            </Button>
                            <Button
                              size="sm"
                              variant={row.is_active ? "danger-quiet" : "secondary"}
                              disabled={isSelf && row.is_active}
                              title={
                                isSelf && row.is_active
                                  ? "Você não pode inativar a própria conta."
                                  : undefined
                              }
                              onClick={() =>
                                setConfirmation({ kind: "active", user: row, active: !row.is_active })
                              }
                            >
                              {row.is_active ? "Inativar" : "Reativar"}
                            </Button>
                          </div>
                        </Td>
                      </Tr>
                    );
                  })
                )}
              </Tbody>
            </Table>
          </TableScroll>
        )}
      </Panel>

      <Panel className="mt-4">
        <PanelHeader title="Matriz resumida de perfis" />
        <TableScroll label="Descrição dos perfis" className="rounded-none border-0 border-t">
          <Table caption="Permissões associadas a cada perfil">
            <Thead><Tr><Th>Perfil</Th><Th>Permissões</Th></Tr></Thead>
            <Tbody>
              {(Object.keys(ROLE_LABELS) as Role[]).map((role) => (
                <Tr key={role}>
                  <TdHeader>{ROLE_LABELS[role]}</TdHeader>
                  <Td className="text-[color:var(--ink-muted)]">{ROLE_DESCRIPTIONS[role]}</Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        </TableScroll>
      </Panel>

      <AccessibleModal
        open={Boolean(editor)}
        title={editor === "create" ? "Criar usuário" : "Editar usuário"}
        description="O backend valida o perfil e impede a remoção do último administrador."
        initialFocusRef={firstInputRef}
        onClose={closeEditor}
        footer={
          <>
            <Button variant="secondary" onClick={closeEditor} disabled={busy}>Cancelar</Button>
            <Button
              type="submit"
              form="user-form"
              variant="primary"
              loading={busy}
              disabled={
                !form.name.trim() ||
                !form.username.trim() ||
                (editor === "create" && Boolean(passwordPolicyError(form.temporaryPassword)))
              }
            >
              {editor === "create" ? "Criar usuário" : "Salvar alterações"}
            </Button>
          </>
        }
      >
        <form id="user-form" onSubmit={saveUser} className="space-y-4">
          <Field label="Nome" required>
            {(props) => (
              <TextInput
                {...props}
                ref={firstInputRef}
                value={form.name}
                disabled={busy}
                onChange={(event) => setForm({ ...form, name: event.target.value })}
              />
            )}
          </Field>
          <Field label="Login" required>
            {(props) => (
              <TextInput
                {...props}
                value={form.username}
                autoCapitalize="none"
                autoComplete="off"
                spellCheck={false}
                disabled={busy}
                onChange={(event) => setForm({ ...form, username: event.target.value })}
              />
            )}
          </Field>
          <Field label="Perfil" hint={ROLE_DESCRIPTIONS[form.role]} required>
            {(props) => (
              <Select
                {...props}
                value={form.role}
                disabled={busy}
                onChange={(event) => setForm({ ...form, role: event.target.value as Role })}
              >
                {(Object.keys(ROLE_LABELS) as Role[]).map((role) => (
                  <option key={role} value={role}>{ROLE_LABELS[role]}</option>
                ))}
              </Select>
            )}
          </Field>
          {editor === "create" && (
            <Field
              label="Senha temporária"
              hint={`${PASSWORD_POLICY_HINT} A troca será exigida no primeiro login.`}
              error={
                form.temporaryPassword.length > 0
                  ? passwordPolicyError(form.temporaryPassword) || undefined
                  : undefined
              }
              required
            >
              {(props) => (
                <TextInput
                  {...props}
                  type="password"
                  minLength={MIN_PASSWORD_LENGTH}
                  value={form.temporaryPassword}
                  autoComplete="new-password"
                  disabled={busy}
                  onChange={(event) => setForm({ ...form, temporaryPassword: event.target.value })}
                />
              )}
            </Field>
          )}
          {dialogError && <Alert tone="danger">{dialogError}</Alert>}
        </form>
      </AccessibleModal>

      <AccessibleModal
        open={Boolean(resetTarget)}
        title="Redefinir senha"
        description={`Defina uma senha temporária para ${resetTarget?.username ?? "o usuário"}.`}
        onClose={() => { if (!busy) { setResetTarget(null); setDialogError(""); } }}
        footer={
          <>
            <Button variant="secondary" disabled={busy} onClick={() => setResetTarget(null)}>Cancelar</Button>
            <Button
              type="submit"
              form="reset-password-form"
              variant="primary"
              loading={busy}
              disabled={Boolean(passwordPolicyError(resetPassword))}
            >
              Redefinir senha
            </Button>
          </>
        }
      >
        <form id="reset-password-form" onSubmit={submitReset} className="space-y-4">
          <Alert tone="warn" live={false}>
            Todas as sessões atuais serão encerradas e a troca da senha será obrigatória
            no próximo login.
          </Alert>
          <Field
            label="Nova senha temporária"
            hint={PASSWORD_POLICY_HINT}
            error={
              resetPassword.length > 0
                ? passwordPolicyError(resetPassword) || undefined
                : undefined
            }
            required
          >
            {(props) => (
              <TextInput
                {...props}
                type="password"
                value={resetPassword}
                minLength={MIN_PASSWORD_LENGTH}
                autoComplete="new-password"
                disabled={busy}
                onChange={(event) => setResetPassword(event.target.value)}
              />
            )}
          </Field>
          {dialogError && <Alert tone="danger">{dialogError}</Alert>}
        </form>
      </AccessibleModal>

      <ConfirmDialog
        open={Boolean(confirmationText)}
        title={confirmationText?.title ?? ""}
        description={confirmationText?.description}
        confirmLabel={confirmationText?.label ?? "Confirmar"}
        tone={confirmationText?.tone}
        busy={busy}
        error={dialogError}
        onConfirm={confirmAction}
        onClose={() => { if (!busy) { setConfirmation(null); setDialogError(""); } }}
      >
        <p className="text-[length:var(--text-sm)] text-[color:var(--ink)]">
          {confirmationText?.body}
        </p>
      </ConfirmDialog>
    </>
  );
}
