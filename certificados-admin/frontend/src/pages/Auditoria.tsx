import { FormEvent, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { classifyError, listAuditLog, AuditEntry } from "../services/api";
import { failureMessage } from "../app/useAsyncData";
import Alert from "../ui/Alert";
import Button from "../ui/Button";
import { Field, Select, TextInput } from "../ui/Field";
import { EmptyState, ErrorState, TableSkeleton } from "../ui/Feedback";
import Icon, { IconName } from "../ui/Icon";
import PageHeader from "../ui/PageHeader";
import Pagination from "../ui/Pagination";
import Panel, { PanelHeader } from "../ui/Panel";
import { Table, TableScroll, Tbody, Td, TdHeader, Th, Thead, Tr } from "../ui/Table";

const PAGE_SIZE = 50;

const CATEGORIES: Record<string, string> = {
  login: "Acessos ao sistema",
  emission: "Emissão",
  duplicate: "Duplicidades",
  revocation: "Revogação",
  reissue: "Reemissão",
  download: "Downloads",
  template: "Templates",
  users: "Gestão de usuários",
  integrity: "Integridade",
  settings: "Configurações",
};

const ACTION_LABELS: Record<string, { label: string; icon: IconName }> = {
  login_success: { label: "Login bem-sucedido", icon: "user" },
  login_failed: { label: "Falha de login", icon: "lock" },
  login_blocked: { label: "Login bloqueado", icon: "warning" },
  logout: { label: "Saída do sistema", icon: "logout" },
  batch_created: { label: "Lote criado", icon: "spreadsheet" },
  emission_completed: { label: "Emissão concluída", icon: "issue" },
  generate: { label: "Emissão concluída", icon: "issue" },
  generation_failed: { label: "Falha na emissão", icon: "error" },
  certificate_duplicate: { label: "Certificado duplicado", icon: "duplicate" },
  certificate_revoked: { label: "Certificado revogado", icon: "revoked" },
  revoke: { label: "Certificado revogado", icon: "revoked" },
  certificate_reissued: { label: "Certificado reemitido", icon: "refresh" },
  reissue: { label: "Certificado reemitido", icon: "refresh" },
  reissue_failed: { label: "Falha na reemissão", icon: "error" },
  certificate_downloaded: { label: "Download individual", icon: "download" },
  certificates_downloaded: { label: "Download em lote", icon: "download" },
  download_zip: { label: "Download em lote", icon: "download" },
  template_version_created: { label: "Versão de template criada", icon: "template" },
  template_version_activated: { label: "Template ativado", icon: "template" },
  template_version_renamed: { label: "Template renomeado", icon: "template" },
  template_version_deleted: { label: "Template excluído", icon: "trash" },
  template_version_create: { label: "Versão de template criada", icon: "template" },
  template_version_activate: { label: "Template ativado", icon: "template" },
  user_created: { label: "Usuário criado", icon: "users" },
  user_updated: { label: "Usuário alterado", icon: "users" },
  user_activated: { label: "Usuário reativado", icon: "users" },
  user_deactivated: { label: "Usuário inativado", icon: "lock" },
  user_password_reset: { label: "Senha redefinida", icon: "lock" },
  password_changed: { label: "Senha própria alterada", icon: "lock" },
  user_sessions_revoked: { label: "Sessões revogadas", icon: "lock" },
  institutional_settings_updated: { label: "Configurações alteradas", icon: "settings" },
  integrity_incident: { label: "Incidente de integridade", icon: "shield" },
  reconcile_active_without_file: { label: "Arquivo ausente detectado", icon: "warning" },
  reconcile_compensation_error: { label: "Falha de reconciliação", icon: "error" },
};

interface Filters {
  category: string;
  action: string;
  actor: string;
  target_id: string;
  date_from: string;
  date_to: string;
}

const EMPTY_FILTERS: Filters = {
  category: "",
  action: "",
  actor: "",
  target_id: "",
  date_from: "",
  date_to: "",
};

function formatTimestamp(value?: string | null): string {
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

function eventDescription(entry: AuditEntry): string {
  const details = entry.details ?? {};
  const parts: string[] = [];
  for (const key of ["generated", "duplicates", "invalid", "failed", "count"] as const) {
    if (typeof details[key] === "number") parts.push(`${key}: ${details[key]}`);
  }
  if (Array.isArray(details.fields) && details.fields.length) {
    parts.push(`campos: ${details.fields.join(", ")}`);
  }
  const subject = entry.actor_username ?? "Sistema";
  const action = ACTION_LABELS[entry.action]?.label ?? entry.action;
  return `${subject} · ${action}${parts.length ? ` · ${parts.join(" · ")}` : ""}`;
}

export default function Auditoria() {
  const [searchParams, setSearchParams] = useSearchParams();
  const applied: Filters = {
    category: searchParams.get("category") ?? "",
    action: searchParams.get("action") ?? "",
    actor: searchParams.get("actor") ?? "",
    target_id: searchParams.get("target_id") ?? "",
    date_from: searchParams.get("date_from") ?? "",
    date_to: searchParams.get("date_to") ?? "",
  };
  const page = Math.max(0, Number(searchParams.get("page") ?? "0") || 0);
  const [draft, setDraft] = useState(applied);
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [offline, setOffline] = useState(false);
  const key = JSON.stringify(applied);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    setOffline(false);
    try {
      const result = await listAuditLog({
        category: applied.category || undefined,
        action: applied.action || undefined,
        actor: applied.actor || undefined,
        target_id: applied.target_id || undefined,
        date_from: applied.date_from || undefined,
        date_to: applied.date_to || undefined,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      });
      setEntries(result.items);
      setTotal(result.total);
    } catch (requestError) {
      setOffline(classifyError(requestError) === "offline");
      setError(failureMessage(requestError, "Não foi possível carregar a auditoria."));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, page]);

  useEffect(() => void load(), [load]);
  useEffect(() => setDraft(applied), [key]); // eslint-disable-line react-hooks/exhaustive-deps

  const apply = (filters: Filters, nextPage = 0) => {
    const params: Record<string, string> = {};
    Object.entries(filters).forEach(([name, value]) => {
      if (value) params[name] = value;
    });
    if (nextPage > 0) params.page = String(nextPage);
    setSearchParams(params);
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    apply(draft);
  };

  const activeCount = Object.values(applied).filter(Boolean).length;

  return (
    <>
      <PageHeader
        title="Auditoria"
        description="Trilha paginada e somente leitura de operações e incidentes."
      />

      <Alert tone="info" live={false} className="mb-4">
        Senhas, documentos, tokens, conteúdo integral do certificado e outros dados
        desnecessários não fazem parte desta consulta.
      </Alert>

      <Panel role="search" className="mb-4">
        <form onSubmit={submit}>
          <div className="grid gap-3 px-4 py-4 sm:grid-cols-2 lg:grid-cols-3 sm:px-5">
            <Field label="Categoria">
              {(props) => (
                <Select
                  {...props}
                  value={draft.category}
                  onChange={(event) => setDraft({ ...draft, category: event.target.value })}
                >
                  <option value="">Todas</option>
                  {Object.entries(CATEGORIES).map(([value, label]) => (
                    <option key={value} value={value}>{label}</option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label="Ação específica">
              {(props) => (
                <Select
                  {...props}
                  value={draft.action}
                  onChange={(event) => setDraft({ ...draft, action: event.target.value })}
                >
                  <option value="">Todas</option>
                  {Object.entries(ACTION_LABELS).map(([value, spec]) => (
                    <option key={value} value={value}>{spec.label}</option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label="Responsável">
              {(props) => (
                <TextInput
                  {...props}
                  value={draft.actor}
                  onChange={(event) => setDraft({ ...draft, actor: event.target.value })}
                />
              )}
            </Field>
            <Field label="Registro afetado" hint="Código, lote ou identificador do usuário.">
              {(props) => (
                <TextInput
                  {...props}
                  value={draft.target_id}
                  onChange={(event) => setDraft({ ...draft, target_id: event.target.value })}
                />
              )}
            </Field>
            <Field label="Data inicial">
              {(props) => (
                <TextInput
                  {...props}
                  type="date"
                  value={draft.date_from}
                  onChange={(event) => setDraft({ ...draft, date_from: event.target.value })}
                />
              )}
            </Field>
            <Field label="Data final">
              {(props) => (
                <TextInput
                  {...props}
                  type="date"
                  min={draft.date_from || undefined}
                  value={draft.date_to}
                  onChange={(event) => setDraft({ ...draft, date_to: event.target.value })}
                />
              )}
            </Field>
          </div>
          <div className="flex flex-wrap gap-2 border-t border-[color:var(--line)] px-4 py-3 sm:px-5">
            <Button type="submit" variant="primary" icon="search">Filtrar</Button>
            {activeCount > 0 && (
              <Button variant="ghost" icon="close" onClick={() => { setDraft(EMPTY_FILTERS); apply(EMPTY_FILTERS); }}>
                Limpar filtros ({activeCount})
              </Button>
            )}
            <Button variant="secondary" icon="refresh" onClick={load}>Atualizar</Button>
          </div>
        </form>
      </Panel>

      <Panel>
        <PanelHeader
          title="Eventos registrados"
          description={activeCount ? "Resultados conforme os filtros aplicados." : "Mais recentes primeiro."}
        />
        {error ? (
          <ErrorState offline={offline} description={error} onRetry={load} />
        ) : (
          <>
            <TableScroll label="Registro de auditoria" className="rounded-none border-0 border-t">
              <Table caption="Eventos de auditoria com data, responsável, ação e registro afetado">
                <Thead>
                  <Tr><Th>Data e hora</Th><Th>Evento</Th><Th className="hidden md:table-cell">Registro afetado</Th></Tr>
                </Thead>
                <Tbody>
                  {loading && entries.length === 0 ? (
                    <TableSkeleton rows={8} columns={3} label="Carregando auditoria" />
                  ) : entries.length === 0 ? (
                    <tr><td colSpan={3}>
                      <EmptyState
                        icon="audit"
                        title={activeCount ? "Nenhum evento encontrado" : "Nenhum evento registrado"}
                        description={activeCount ? "Ajuste ou limpe os filtros para ampliar a consulta." : "As operações auditáveis aparecerão aqui."}
                      />
                    </td></tr>
                  ) : entries.map((entry) => {
                    const spec = ACTION_LABELS[entry.action] ?? { label: entry.action, icon: "info" as IconName };
                    return (
                      <Tr key={entry.id}>
                        <TdHeader className="whitespace-nowrap align-top font-normal">{formatTimestamp(entry.created_at)}</TdHeader>
                        <Td className="align-top">
                          <span className="flex items-start gap-2">
                            <Icon name={spec.icon} size={16} className="mt-0.5 shrink-0 text-[color:var(--ink-muted)]" />
                            <span>
                              <span className="block text-[color:var(--ink)]">{eventDescription(entry)}</span>
                              <span className="mt-0.5 block text-[length:var(--text-xs)] text-[color:var(--ink-muted)]">{entry.action}</span>
                            </span>
                          </span>
                        </Td>
                        <Td className="hidden align-top md:table-cell">
                          {entry.target_id ? <span className="font-[family-name:var(--font-mono)] text-[length:var(--text-xs)]">{entry.target_id}</span> : "—"}
                        </Td>
                      </Tr>
                    );
                  })}
                </Tbody>
              </Table>
            </TableScroll>
            <Pagination
              page={page}
              pageSize={PAGE_SIZE}
              total={total}
              loading={loading}
              itemNoun="evento"
              itemNounPlural="eventos"
              onPageChange={(next) => apply(applied, next)}
            />
          </>
        )}
      </Panel>
    </>
  );
}
