/**
 * Histórico — the register the secretariat works in daily.
 *
 * Design decisions worth keeping:
 *  - Filters live in a compact bar and are submitted as a form, so Enter works
 *    from any field and the whole set applies at once instead of firing a
 *    request per keystroke.
 *  - Filters are mirrored into the URL query string, so a filtered view is a
 *    shareable link and survives a refresh.
 *  - Status is never colour-only: every row carries an icon + word badge.
 *  - Below `md` the table becomes a list of records, because a seven-column
 *    table at 320px is unusable no matter how it scrolls.
 *
 * Accessible names pinned by the existing tests are preserved verbatim:
 * checkbox names containing the participant, "Selecionar página", "Baixar ZIP
 * (n)", "Revogar", "Motivo", "Confirmar revogação".
 */
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import PageHeader from "../ui/PageHeader";
import Panel, { PanelHeader } from "../ui/Panel";
import Alert from "../ui/Alert";
import Button, { IconButton } from "../ui/Button";
import Icon from "../ui/Icon";
import Pagination from "../ui/Pagination";
import StatusBadge, { certificateStatus } from "../ui/StatusBadge";
import AccessibleModal from "../components/AccessibleModal";
import ConfirmDialog from "../ui/ConfirmDialog";
import { Field, Select, TextInput, Textarea, Checkbox } from "../ui/Field";
import { EmptyState, ErrorState, TableSkeleton } from "../ui/Feedback";
import { Table, TableScroll, Tbody, Td, TdHeader, Th, Thead, Tr } from "../ui/Table";
import { cn } from "../ui/cn";
import { failureMessage } from "../app/useAsyncData";
import { useAuth } from "../app/AuthContext";
import { useIsWide } from "../app/useMediaQuery";
import {
  CERTIFICATE_TYPES,
  certificateTypeLabel,
} from "../domain/certificateTypes";
import {
  AdminCertificate,
  classifyError,
  downloadCertificateFile,
  downloadCertificatesZip,
  getCertificate,
  listCertificates,
  reissueCertificate,
  revokeCertificate,
} from "../services/api";

const PAGE_SIZE = 20;
const MAX_ZIP_SELECTION = 200;

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function canDownload(cert: AdminCertificate) {
  return cert.status === "ativo" && cert.download_available;
}

function IntegrityLabel({ cert }: { cert: AdminCertificate }) {
  if (cert.integrity_status === "blocked" || cert.integrity_blocked) {
    return (
      <span className="inline-flex items-center gap-1 text-[length:var(--text-xs)] font-medium text-[color:var(--danger-fg)]">
        <Icon name="warning" size={12} /> Integridade bloqueada
      </span>
    );
  }
  if (cert.integrity_status === "verified") {
    return (
      <span className="inline-flex items-center gap-1 text-[length:var(--text-xs)] text-[color:var(--ok-fg)]">
        <Icon name="shield" size={12} /> Integridade verificada
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-[length:var(--text-xs)] text-[color:var(--ink-subtle)]">
      <Icon name="info" size={12} /> Sem checksum legado
    </span>
  );
}

function formatTimestamp(value?: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "—" : parsed.toLocaleString("pt-BR");
}

interface Filters {
  name: string;
  code: string;
  course: string;
  event: string;
  certificate_type: string;
  status: string;
  date_from: string;
  date_to: string;
  batch_id: string;
}

const EMPTY_FILTERS: Filters = {
  name: "",
  code: "",
  course: "",
  event: "",
  certificate_type: "",
  status: "",
  date_from: "",
  date_to: "",
  batch_id: "",
};

export default function Historico() {
  const { can } = useAuth();
  const isWide = useIsWide();
  const [searchParams, setSearchParams] = useSearchParams();

  /* Applied filters come from the URL, so a filtered view is linkable. */
  const applied: Filters = {
    name: searchParams.get("name") ?? "",
    code: searchParams.get("code") ?? "",
    course: searchParams.get("course") ?? "",
    event: searchParams.get("event") ?? "",
    certificate_type: searchParams.get("certificate_type") ?? "",
    status: searchParams.get("status") ?? "",
    date_from: searchParams.get("date_from") ?? "",
    date_to: searchParams.get("date_to") ?? "",
    batch_id: searchParams.get("batch_id") ?? "",
  };
  const page = Math.max(0, Number(searchParams.get("page") ?? "0") || 0);

  /* Draft filters are what the operator is typing right now. */
  const [draft, setDraft] = useState<Filters>(applied);

  const [items, setItems] = useState<AdminCertificate[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [firstLoad, setFirstLoad] = useState(true);
  const [error, setError] = useState("");
  const [offline, setOffline] = useState(false);

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [downloading, setDownloading] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [downloadStatus, setDownloadStatus] = useState("");

  const [revokeTarget, setRevokeTarget] = useState<AdminCertificate | null>(null);
  const [reason, setReason] = useState("");
  const [revokeError, setRevokeError] = useState("");
  const [revoking, setRevoking] = useState(false);
  const reasonRef = useRef<HTMLTextAreaElement>(null);

  const [detail, setDetail] = useState<AdminCertificate | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [reissueTarget, setReissueTarget] = useState<AdminCertificate | null>(null);
  const [reissuing, setReissuing] = useState(false);
  const [reissueError, setReissueError] = useState("");

  const appliedKey = JSON.stringify(applied);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    setOffline(false);
    try {
      const data = await listCertificates({
        name: applied.name || undefined,
        code: applied.code || undefined,
        course: applied.course || undefined,
        event: applied.event || undefined,
        certificate_type: applied.certificate_type || undefined,
        status: applied.status || undefined,
        date_from: applied.date_from || undefined,
        date_to: applied.date_to || undefined,
        batch_id: applied.batch_id || undefined,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      });
      setItems(data.items);
      setTotal(data.total);
    } catch (requestError) {
      setOffline(classifyError(requestError) === "offline");
      setError(
        failureMessage(requestError, "Não foi possível carregar os certificados."),
      );
    } finally {
      setLoading(false);
      setFirstLoad(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appliedKey, page]);

  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => {
      if (!cancelled) void load();
    });
    return () => {
      cancelled = true;
    };
  }, [load]);

  /* Keep the draft in step when the URL changes from outside (e.g. a dashboard
   * link that arrives with ?status=revogado already set). */
  useEffect(() => {
    setDraft(applied);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appliedKey]);

  const updateParams = (next: Filters, nextPage: number) => {
    const params: Record<string, string> = {};
    Object.entries(next).forEach(([key, value]) => {
      if (value) params[key] = value;
    });
    if (nextPage > 0) params.page = String(nextPage);
    setSearchParams(params, { replace: false });
  };

  const submitFilters = (event: FormEvent) => {
    event.preventDefault();
    updateParams(draft, 0);
  };

  const clearFilters = () => {
    setDraft(EMPTY_FILTERS);
    updateParams(EMPTY_FILTERS, 0);
  };

  const activeFilterCount = Object.values(applied).filter(Boolean).length;

  const availableOnPage = items.filter(canDownload).map((item) => item.unique_code);
  const pageSelected =
    availableOnPage.length > 0 && availableOnPage.every((code) => selected.has(code));

  const toggle = (code: string) => {
    if (!selected.has(code) && selected.size >= MAX_ZIP_SELECTION) {
      setDownloadStatus(
        `Selecione no máximo ${MAX_ZIP_SELECTION} certificados por arquivo ZIP.`,
      );
      return;
    }
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  const togglePage = () => {
    setSelected((current) => {
      const next = new Set(current);
      availableOnPage.forEach((code) => {
        if (pageSelected) next.delete(code);
        else if (next.size < MAX_ZIP_SELECTION) next.add(code);
      });
      return next;
    });
  };

  const handleBatchDownload = async () => {
    if (!selected.size) return;
    setDownloading(true);
    setProgress(null);
    setDownloadStatus("");
    try {
      const result = await downloadCertificatesZip([...selected], setProgress);
      saveBlob(result.blob, "certificados.zip");
      if (result.skippedCodes.length) {
        setDownloadStatus(
          `ZIP gerado parcialmente. ${result.skippedCodes.length} certificado(s) ficaram indisponíveis: ${result.skippedCodes.join(", ")}.`,
        );
      } else {
        setDownloadStatus(`${selected.size} certificado(s) baixados com sucesso.`);
      }
      setSelected(new Set());
    } catch (requestError) {
      setDownloadStatus(
        failureMessage(requestError, "Não foi possível gerar o arquivo ZIP."),
      );
    } finally {
      setDownloading(false);
      setProgress(null);
    }
  };

  const handleSingleDownload = async (cert: AdminCertificate) => {
    setDownloadStatus("");
    try {
      const blob = await downloadCertificateFile(cert.unique_code);
      saveBlob(blob, `${cert.participant_name.replace(/[^\p{L}\p{N}._-]+/gu, "_")}.pdf`);
    } catch (requestError) {
      setDownloadStatus(
        failureMessage(requestError, "Não foi possível baixar o certificado."),
      );
    }
  };

  const openRevoke = (cert: AdminCertificate) => {
    setRevokeTarget(cert);
    setReason("");
    setRevokeError("");
  };

  const closeRevoke = () => {
    if (!revoking) setRevokeTarget(null);
  };

  const confirmRevoke = async () => {
    if (!revokeTarget) return;
    const cleanReason = reason.trim();
    if (cleanReason.length < 5) {
      setRevokeError("Informe um motivo com pelo menos 5 caracteres.");
      reasonRef.current?.focus();
      return;
    }
    setRevoking(true);
    setRevokeError("");
    try {
      await revokeCertificate(revokeTarget.unique_code, cleanReason);
      setSelected((current) => {
        const next = new Set(current);
        next.delete(revokeTarget.unique_code);
        return next;
      });
      setRevokeTarget(null);
      await load();
    } catch (requestError) {
      setRevokeError(
        failureMessage(requestError, "Não foi possível revogar o certificado."),
      );
    } finally {
      setRevoking(false);
    }
  };

  const openDetail = async (cert: AdminCertificate) => {
    setDetail(cert);
    setDetailLoading(true);
    setDetailError("");
    try {
      setDetail(await getCertificate(cert.unique_code));
    } catch (requestError) {
      setDetailError(
        failureMessage(requestError, "Não foi possível carregar todos os detalhes."),
      );
    } finally {
      setDetailLoading(false);
    }
  };

  const confirmReissue = async () => {
    if (!reissueTarget || reissuing) return;
    setReissuing(true);
    setReissueError("");
    try {
      const updated = await reissueCertificate(reissueTarget.unique_code);
      setDownloadStatus(`Certificado de ${updated.participant_name} reemitido com sucesso.`);
      setReissueTarget(null);
      if (detail?.unique_code === updated.unique_code) setDetail(updated);
      await load();
    } catch (requestError) {
      setReissueError(
        failureMessage(requestError, "Não foi possível reemitir o certificado."),
      );
    } finally {
      setReissuing(false);
    }
  };

  const columnCount = can("certificates.download") ? 9 : 8;

  return (
    <>
      <PageHeader
        title="Histórico de certificados"
        description="Consulte, detalhe, baixe, revogue e reemita conforme seu perfil."
      />

      {/* ── Filters ─────────────────────────────────────────────────────── */}
      <Panel role="search" className="mb-4">
        <form onSubmit={submitFilters}>
          <div className="grid grid-cols-1 gap-3 px-4 py-4 sm:grid-cols-2 sm:px-5 lg:grid-cols-4">
            <Field label="Nome do participante">
              {(props) => (
                <TextInput
                  {...props}
                  value={draft.name}
                  onChange={(event) => setDraft({ ...draft, name: event.target.value })}
                />
              )}
            </Field>
            <Field label="Código de validação">
              {(props) => (
                <TextInput
                  {...props}
                  value={draft.code}
                  className="font-[family-name:var(--font-mono)]"
                  onChange={(event) => setDraft({ ...draft, code: event.target.value })}
                />
              )}
            </Field>
            <Field label="Curso">
              {(props) => (
                <TextInput
                  {...props}
                  value={draft.course}
                  onChange={(event) => setDraft({ ...draft, course: event.target.value })}
                />
              )}
            </Field>
            <Field label="Evento">
              {(props) => (
                <TextInput
                  {...props}
                  value={draft.event}
                  onChange={(event) => setDraft({ ...draft, event: event.target.value })}
                />
              )}
            </Field>
            <Field label="Situação">
              {(props) => (
                <Select
                  {...props}
                  value={draft.status}
                  onChange={(event) => setDraft({ ...draft, status: event.target.value })}
                >
                  <option value="">Todas</option>
                  <option value="ativo">Ativo</option>
                  <option value="revogado">Revogado</option>
                  <option value="failed">Falha na emissão</option>
                  <option value="pending">Pendente</option>
                </Select>
              )}
            </Field>
            <Field label="Tipo do certificado">
              {(props) => (
                <Select
                  {...props}
                  value={draft.certificate_type}
                  onChange={(event) =>
                    setDraft({ ...draft, certificate_type: event.target.value })
                  }
                >
                  <option value="">Todos</option>
                  {CERTIFICATE_TYPES.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </Select>
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
            <Field label="Identificador do lote">
              {(props) => (
                <TextInput
                  {...props}
                  value={draft.batch_id}
                  className="font-[family-name:var(--font-mono)]"
                  onChange={(event) => setDraft({ ...draft, batch_id: event.target.value })}
                />
              )}
            </Field>
          </div>

          <div className="flex flex-wrap items-center gap-2 border-t border-[color:var(--line)] px-4 py-3 sm:px-5">
            <Button type="submit" variant="primary" icon="search">
              Buscar
            </Button>
            {activeFilterCount > 0 && (
              <Button variant="ghost" icon="close" onClick={clearFilters}>
                Limpar filtros ({activeFilterCount})
              </Button>
            )}
          </div>
        </form>
      </Panel>

      {/* ── Bulk actions ────────────────────────────────────────────────── */}
      {can("certificates.download") && (
        <div className="mb-4 flex flex-wrap items-center gap-2 rounded-[var(--radius-md)] border border-[color:var(--line)] bg-[var(--surface)] px-3 py-2.5">
          <Button
            size="sm"
            variant="secondary"
            onClick={togglePage}
            disabled={!availableOnPage.length}
          >
            {pageSelected ? "Remover página" : "Selecionar página"}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setSelected(new Set())}
            disabled={!selected.size}
          >
            Limpar seleção
          </Button>
          <Button
            size="sm"
            variant="primary"
            icon="download"
            onClick={handleBatchDownload}
            disabled={!selected.size}
            loading={downloading}
          >
            {downloading ? "Gerando ZIP…" : `Baixar ZIP (${selected.size})`}
          </Button>

          {downloading && (
            <div
              role="status"
              aria-live="polite"
              className="flex items-center gap-2 text-[length:var(--text-sm)] text-[color:var(--ink-muted)]"
            >
              <progress
                value={progress ?? undefined}
                max={100}
                aria-label="Progresso do download"
                className="h-1.5 w-28"
              />
              {progress == null ? "Recebendo arquivo…" : `${progress}%`}
            </div>
          )}

          {selected.size > 0 && !downloading && (
            <p className="ml-auto text-[length:var(--text-xs)] text-[color:var(--ink-muted)]">
              Máximo de {MAX_ZIP_SELECTION} por arquivo
            </p>
          )}
        </div>
      )}

      {downloadStatus && (
        <Alert tone="warn" className="mb-4">
          {downloadStatus}
        </Alert>
      )}

      {/* ── Results ─────────────────────────────────────────────────────── */}
      <Panel>
        <PanelHeader
          title="Certificados"
          description={
            activeFilterCount > 0
              ? "Resultados filtrados. Limpe os filtros para ver todo o registro."
              : undefined
          }
        />

        {error && !firstLoad ? (
          <ErrorState offline={offline} description={error} onRetry={load} />
        ) : (
          <>
            {/* Exactly one layout is rendered — see useMediaQuery for why. */}
            {isWide ? (
              <TableScroll label="Certificados emitidos" className="rounded-none border-0 border-t">
                <Table caption="Certificados emitidos, com situação e ações disponíveis">
                  <Thead>
                    <Tr>
                      {can("certificates.download") && (
                        <Th className="w-10">
                          <span className="sr-only">Seleção</span>
                        </Th>
                      )}
                      <Th>Participante</Th>
                      <Th>Curso</Th>
                      <Th>Evento</Th>
                      <Th>Tipo</Th>
                      <Th>Emissão</Th>
                      <Th>Código</Th>
                      <Th>Situação</Th>
                      <Th>
                        <span className="sr-only">Ações</span>
                      </Th>
                    </Tr>
                  </Thead>
                  <Tbody>
                    {loading && firstLoad ? (
                      <TableSkeleton rows={6} columns={columnCount} />
                    ) : items.length === 0 ? (
                      <tr>
                        <td colSpan={columnCount}>
                          <NoResults
                            filtered={activeFilterCount > 0}
                            onClear={clearFilters}
                          />
                        </td>
                      </tr>
                    ) : (
                      items.map((cert) => {
                        const status = certificateStatus(cert);
                        const available = canDownload(cert);
                        return (
                          <Tr key={cert.unique_code}>
                            {can("certificates.download") && (
                              <Td>
                                <Checkbox
                                  compact
                                  labelHidden
                                  label={`Selecionar certificado de ${cert.participant_name}`}
                                  checked={selected.has(cert.unique_code)}
                                  disabled={!available}
                                  onChange={() => toggle(cert.unique_code)}
                                />
                              </Td>
                            )}
                            <TdHeader>{cert.participant_name}</TdHeader>
                            <Td className="text-[color:var(--ink-muted)]">
                              {cert.course_name || "—"}
                            </Td>
                            <Td className="text-[color:var(--ink-muted)]">
                              {cert.event_name || "—"}
                            </Td>
                            <Td className="text-[color:var(--ink-muted)]">
                              {certificateTypeLabel(
                                cert.certificate_type,
                                cert.certificate_type_label,
                              )}
                            </Td>
                            <Td className="whitespace-nowrap text-[color:var(--ink-muted)]">
                              {cert.issue_date || "—"}
                            </Td>
                            <Td mono>{cert.unique_code}</Td>
                            <Td>
                              <span className="flex flex-col items-start gap-1">
                                <StatusBadge tone={status.tone} icon={status.icon}>
                                  {status.label}
                                </StatusBadge>
                                <IntegrityLabel cert={cert} />
                              </span>
                            </Td>
                            <Td>
                              <div className="flex items-center justify-end gap-1">
                                <IconButton
                                  size="sm"
                                  icon="eye"
                                  label={`Ver detalhes de ${cert.participant_name}`}
                                  onClick={() => void openDetail(cert)}
                                />
                                {can("certificates.download") && (
                                  <IconButton
                                    size="sm"
                                    icon="download"
                                    label={`Baixar certificado de ${cert.participant_name}`}
                                    disabled={!available}
                                    onClick={() => handleSingleDownload(cert)}
                                  />
                                )}
                                {can("certificates.revoke") &&
                                  cert.status !== "revogado" && (
                                    <Button
                                      size="sm"
                                      variant="danger-quiet"
                                      onClick={() => openRevoke(cert)}
                                    >
                                      Revogar
                                    </Button>
                                  )}
                                {can("certificates.reissue") &&
                                  cert.status === "ativo" && (
                                    <Button
                                      size="sm"
                                      variant="secondary"
                                      onClick={() => setReissueTarget(cert)}
                                    >
                                      Reemitir
                                    </Button>
                                  )}
                              </div>
                            </Td>
                          </Tr>
                        );
                      })
                    )}
                  </Tbody>
                </Table>
              </TableScroll>
            ) : (
              /* Narrow: records as a list — a 7-column table is unusable at 320px */
              <div className="border-t border-[color:var(--line)]">
              {loading && firstLoad ? (
                <p role="status" className="px-4 py-6 text-[length:var(--text-sm)] text-[color:var(--ink-muted)]">
                  Carregando certificados…
                </p>
              ) : items.length === 0 ? (
                <NoResults filtered={activeFilterCount > 0} onClear={clearFilters} />
              ) : (
                <ul className="divide-y divide-[color:var(--line)]">
                  {items.map((cert) => {
                    const status = certificateStatus(cert);
                    const available = canDownload(cert);
                    return (
                      <li key={cert.unique_code} className="px-4 py-3">
                        <div className="flex items-start gap-2">
                          {can("certificates.download") && (
                            <Checkbox
                              compact
                              labelHidden
                              label={`Selecionar certificado de ${cert.participant_name}`}
                              checked={selected.has(cert.unique_code)}
                              disabled={!available}
                              onChange={() => toggle(cert.unique_code)}
                              className="-ml-2 mt-0.5"
                            />
                          )}
                          <div className="min-w-0 flex-1">
                            <p className="font-medium text-[color:var(--ink)]">
                              {cert.participant_name}
                            </p>
                            <p className="mt-0.5 text-[length:var(--text-sm)] text-[color:var(--ink-muted)]">
                              {cert.event_name || cert.course_name || "—"}
                            </p>
                            <p className="mt-0.5 text-[length:var(--text-xs)] text-[color:var(--ink-subtle)]">
                              Tipo: {certificateTypeLabel(cert.certificate_type, cert.certificate_type_label)}
                            </p>
                            <p className="mt-1 font-[family-name:var(--font-mono)] text-[length:var(--text-xs)] text-[color:var(--ink-muted)]">
                              {cert.unique_code}
                            </p>
                            <div className="mt-2 flex flex-wrap items-center gap-2">
                              <StatusBadge tone={status.tone} icon={status.icon}>
                                {status.label}
                              </StatusBadge>
                              {cert.issue_date && (
                                <span className="text-[length:var(--text-xs)] text-[color:var(--ink-subtle)]">
                                  {cert.issue_date}
                                </span>
                              )}
                              <IntegrityLabel cert={cert} />
                            </div>
                            <div className="mt-2.5 flex flex-wrap gap-2">
                              <Button size="sm" variant="secondary" icon="eye" onClick={() => void openDetail(cert)}>
                                Detalhes
                              </Button>
                              {can("certificates.download") && (
                                <Button
                                  size="sm"
                                  variant="secondary"
                                  icon="download"
                                  disabled={!available}
                                  onClick={() => handleSingleDownload(cert)}
                                >
                                  Baixar
                                </Button>
                              )}
                              {can("certificates.revoke") && cert.status !== "revogado" && (
                                <Button
                                  size="sm"
                                  variant="danger-quiet"
                                  onClick={() => openRevoke(cert)}
                                >
                                  Revogar
                                </Button>
                              )}
                              {can("certificates.reissue") && cert.status === "ativo" && (
                                <Button
                                  size="sm"
                                  variant="secondary"
                                  icon="refresh"
                                  onClick={() => setReissueTarget(cert)}
                                >
                                  Reemitir
                                </Button>
                              )}
                            </div>
                          </div>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
              </div>
            )}

            <Pagination
              page={page}
              pageSize={PAGE_SIZE}
              total={total}
              loading={loading && !firstLoad}
              itemNoun="certificado"
              itemNounPlural="certificados"
              onPageChange={(nextPage) => updateParams(applied, nextPage)}
            />
          </>
        )}
      </Panel>

      {/* ── Revoke confirmation ─────────────────────────────────────────── */}
      <AccessibleModal
        open={Boolean(revokeTarget)}
        title="Revogar certificado"
        description="A revogação é permanente e fica registrada na auditoria."
        onClose={closeRevoke}
        initialFocusRef={reasonRef}
        dismissOnBackdrop={false}
        footer={
          <>
            <Button variant="secondary" onClick={closeRevoke} disabled={revoking}>
              Cancelar
            </Button>
            <Button
              variant="danger"
              onClick={confirmRevoke}
              loading={revoking}
              disabled={reason.trim().length < 5}
            >
              Confirmar revogação
            </Button>
          </>
        }
      >
        <p className="text-[length:var(--text-sm)] text-[color:var(--ink)]">
          O certificado de <strong>{revokeTarget?.participant_name}</strong> deixará
          de ser válido na consulta pública e não poderá mais ser baixado.
        </p>
        <p className="mt-1 font-[family-name:var(--font-mono)] text-[length:var(--text-xs)] text-[color:var(--ink-muted)]">
          {revokeTarget?.unique_code}
        </p>

        <div className="mt-4">
          <label
            htmlFor="revoke-reason"
            className="text-[length:var(--text-sm)] font-medium text-[color:var(--ink)]"
          >
            Motivo{" "}
            <span className="text-[color:var(--danger-fg)]" aria-hidden="true">
              *
            </span>
            <span className="sr-only">(obrigatório)</span>
          </label>
          <Textarea
            ref={reasonRef}
            id="revoke-reason"
            aria-label="Motivo"
            value={reason}
            minLength={5}
            maxLength={500}
            rows={4}
            aria-describedby="revoke-help"
            onChange={(event) => setReason(event.target.value)}
            className="mt-1.5"
          />
          <p
            id="revoke-help"
            className="mt-1 text-[length:var(--text-xs)] text-[color:var(--ink-subtle)]"
          >
            Entre 5 e 500 caracteres. Este texto fica registrado na auditoria.
          </p>
        </div>

        {revokeError && (
          <Alert tone="danger" className="mt-3">
            {revokeError}
          </Alert>
        )}
      </AccessibleModal>

      {/* ── Detail ──────────────────────────────────────────────────────── */}
      <AccessibleModal
        open={Boolean(detail)}
        title="Detalhes do certificado"
        onClose={() => setDetail(null)}
        size="lg"
        footer={
          <Button variant="secondary" onClick={() => setDetail(null)}>
            Fechar
          </Button>
        }
      >
        {detailLoading && (
          <p role="status" className="mb-3 text-[length:var(--text-sm)] text-[color:var(--ink-muted)]">
            Carregando detalhes…
          </p>
        )}
        {detailError && <Alert tone="warn" className="mb-3">{detailError}</Alert>}
        {detail && <CertificateDetail cert={detail} />}
      </AccessibleModal>

      <ConfirmDialog
        open={Boolean(reissueTarget)}
        title="Reemitir certificado"
        description="O arquivo atual será regenerado com o contexto institucional preservado da emissão."
        confirmLabel="Confirmar reemissão"
        tone="primary"
        busy={reissuing}
        error={reissueError}
        onConfirm={confirmReissue}
        onClose={() => {
          if (!reissuing) {
            setReissueTarget(null);
            setReissueError("");
          }
        }}
      >
        <p className="text-[length:var(--text-sm)] text-[color:var(--ink)]">
          Reemitir o certificado de <strong>{reissueTarget?.participant_name}</strong>,
          código <span className="font-[family-name:var(--font-mono)]">{reissueTarget?.unique_code}</span>?
          A operação ficará registrada na auditoria.
        </p>
      </ConfirmDialog>
    </>
  );
}

function NoResults({
  filtered,
  onClear,
}: {
  filtered: boolean;
  onClear: () => void;
}) {
  return filtered ? (
    <EmptyState
      icon="search"
      title="Nenhum certificado corresponde aos filtros"
      description="Verifique a grafia do nome ou do código. A busca por nome ignora acentos e maiúsculas."
      action={
        <Button variant="secondary" icon="close" onClick={onClear}>
          Limpar filtros
        </Button>
      }
    />
  ) : (
    <EmptyState
      icon="certificate"
      title="Nenhum certificado emitido ainda"
      description="Os certificados aparecem aqui assim que a primeira planilha for processada."
    />
  );
}

/** Detail view. Shows only what the operator needs; no participant document. */
function CertificateDetail({ cert }: { cert: AdminCertificate }) {
  const status = certificateStatus(cert);
  const rows: { label: string; value: React.ReactNode }[] = [
    { label: "Participante", value: cert.participant_name },
    { label: "Curso", value: cert.course_name || "—" },
    { label: "Evento", value: cert.event_name || "—" },
    {
      label: "Tipo do certificado",
      value: certificateTypeLabel(cert.certificate_type, cert.certificate_type_label),
    },
    {
      label: "Carga horária",
      value: cert.workload_hours ? `${cert.workload_hours} horas` : "—",
    },
    { label: "Data de emissão", value: cert.issue_date || "—" },
    {
      label: "Código de validação",
      value: (
        <span className="font-[family-name:var(--font-mono)]">{cert.unique_code}</span>
      ),
    },
    {
      label: "Situação",
      value: (
        <StatusBadge tone={status.tone} icon={status.icon}>
          {status.label}
        </StatusBadge>
      ),
    },
    { label: "Integridade", value: <IntegrityLabel cert={cert} /> },
    {
      label: "Template",
      value: cert.template_used
        ? `${cert.template_used}${cert.template_version_id ? ` · versão ${cert.template_version_id}` : ""}`
        : cert.template_version_id
          ? `Versão ${cert.template_version_id}`
          : "Registro legado sem versão",
    },
    {
      label: "Responsável pela emissão",
      value: cert.issued_by
        ? `${cert.issued_by.name || cert.issued_by.username || `Usuário ${cert.issued_by.id}`}${cert.issued_by.username && cert.issued_by.name ? ` (${cert.issued_by.username})` : ""}`
        : "Registro legado sem responsável",
    },
    {
      label: "Lote",
      value: cert.batch_id ? (
        <span className="font-[family-name:var(--font-mono)]">{cert.batch_id}</span>
      ) : "Emissão sem lote persistente",
    },
    { label: "Início", value: cert.start_date || "—" },
    { label: "Término", value: cert.end_date || "—" },
    {
      label: "Reemissões",
      value: cert.reissue_count
        ? `${cert.reissue_count} · última em ${formatTimestamp(cert.reissued_at)}`
        : "Nenhuma",
    },
    ...(cert.status === "revogado"
      ? [
          { label: "Revogado em", value: formatTimestamp(cert.revoked_at) },
          { label: "Motivo da revogação", value: cert.revoke_reason || "—" },
        ]
      : []),
    { label: "Armazenamento", value: cert.storage_provider || "—" },
  ];

  return (
    <dl className="divide-y divide-[color:var(--line)]">
      {rows.map((row) => (
        <div
          key={row.label}
          className={cn(
            "grid gap-1 py-2.5",
            "sm:grid-cols-[11rem_1fr] sm:items-baseline sm:gap-4",
          )}
        >
          <dt className="text-[length:var(--text-sm)] text-[color:var(--ink-muted)]">
            {row.label}
          </dt>
          <dd className="min-w-0 break-words text-[length:var(--text-sm)] text-[color:var(--ink)]">
            {row.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}
