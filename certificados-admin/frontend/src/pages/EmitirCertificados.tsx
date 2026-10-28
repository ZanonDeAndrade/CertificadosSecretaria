import { ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "../app/AuthContext";
import { failureMessage, useAsyncData } from "../app/useAsyncData";
import CertificateSubject from "../components/CertificateSubject";
import {
  cancelEmissionBatch,
  disconnectGoogleDrive,
  EmissionBatch,
  GenerationSummary,
  getEmissionBatch,
  getGoogleDrivePickerSession,
  getGoogleDriveStatus,
  listBodyVariables,
  resumeEmissionBatch,
  retryEmissionBatch,
  selectGoogleDriveFolder,
  spreadsheetTemplateUrlFor,
  SpreadsheetPreview,
  startEmissionBatch,
  startGoogleDriveOAuth,
  validateSpreadsheet,
} from "../services/api";
import { pickGoogleDriveFolder } from "../lib/googlePicker";
import { createUuid } from "../lib/uuid";
import {
  CERTIFICATE_TYPES,
  MAX_WORK_AUTHORS,
  certificateTypeLabel,
  isPerWorkType,
} from "../domain/certificateTypes";
import Alert from "../ui/Alert";
import Button, { AnchorButton, LinkButton } from "../ui/Button";
import ConfirmDialog from "../ui/ConfirmDialog";
import { Field, Select, Textarea, TextInput } from "../ui/Field";
import Icon from "../ui/Icon";
import PageHeader from "../ui/PageHeader";
import Panel, { PanelBody, PanelHeader } from "../ui/Panel";
import Stepper from "../ui/Stepper";
import { Table, TableScroll, Tbody, Td, TdHeader, Th, Thead, Tr } from "../ui/Table";
import { cn } from "../ui/cn";

type Step = "upload" | "preview" | "destination" | "progress" | "done";

const STEPS = [
  { id: "upload", label: "Planilha" },
  { id: "preview", label: "Conferência" },
  { id: "destination", label: "Destino" },
  { id: "progress", label: "Emissão" },
  { id: "done", label: "Resultado" },
];

/* Pre-filled for ordinary types. A per-work type (the Mostra) starts blank:
 * its automatic body applies, and this text would print the certificate as an
 * ordinary one ("participou da atividade…"). */
const DEFAULT_BODY_TEXT =
  "participou da atividade descrita neste certificado, com carga horária total de " +
  "{{carga_horaria}} horas.";

interface StoredBatch {
  idempotencyKey: string;
  batchId?: string;
}

interface FolderChoice {
  folderId: string;
  folderName: string;
}

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function exportInvalidRows(preview: SpreadsheetPreview) {
  const escape = (value: string) => `"${value.replace(/"/g, '""')}"`;
  const rows = [
    "linha;erros",
    ...preview.invalid.map(
      (row) => `${row.row_number};${escape(row.errors.join("; "))}`,
    ),
  ];
  saveBlob(
    new Blob(["\ufeff", rows.join("\n")], { type: "text/csv;charset=utf-8" }),
    "relatorio-erros-emissao.csv",
  );
}

/* Per-work batches: one row per work, with every author it will list. */
function WorkRowsTable({ rows }: { rows: SpreadsheetPreview["valid"] }) {
  return (
    <Table caption="Trabalhos aptos para emissão">
      <Thead>
        <Tr>
          <Th>Linha</Th>
          <Th>Trabalho</Th>
          <Th>Autores</Th>
          <Th>Carga</Th>
          <Th>Emissão</Th>
        </Tr>
      </Thead>
      <Tbody>
        {rows.map((row) => {
          const authors = row.autores?.length ? row.autores : [row.nome];
          return (
            <Tr key={row.row_number}>
              <Td>{row.row_number}</Td>
              <TdHeader>
                {row.titulo_trabalho}
                <span className="block text-[length:var(--text-xs)] font-normal text-[color:var(--ink-muted)]">
                  {row.evento}
                </span>
              </TdHeader>
              <Td>
                <ul aria-label={`Autores do trabalho da linha ${row.row_number}`}>
                  {authors.map((name, index) => (
                    <li key={`${index}-${name}`}>{name}</li>
                  ))}
                </ul>
              </Td>
              <Td>{row.carga_horaria == null ? "—" : `${row.carga_horaria}h`}</Td>
              <Td>{row.data_emissao}</Td>
            </Tr>
          );
        })}
      </Tbody>
    </Table>
  );
}

function fallbackSummary(batch: EmissionBatch): GenerationSummary {
  return {
    batch_id: batch.id,
    generated: [],
    generated_count: batch.generated_count,
    duplicates: [],
    duplicate_count: batch.duplicate_count,
    failed: [],
    failed_count: batch.failed_count,
    invalid: batch.invalid_report,
    invalid_count: batch.invalid_count,
    total_rows: batch.total_rows,
  };
}

export default function EmitirCertificados() {
  const { user } = useAuth();
  const storageKey = `certificados:emission-batch:${user?.id ?? "session"}`;
  const [step, setStep] = useState<Step>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [dataEmissao, setDataEmissao] = useState("");
  const [certificateType, setCertificateType] = useState("");
  const [certificateTypeError, setCertificateTypeError] = useState("");
  const [textoPadrao, setTextoPadrao] = useState(DEFAULT_BODY_TEXT);
  // The insert buttons come from the backend allowlist, never a local copy.
  const bodyVariables = useAsyncData(listBodyVariables, []);
  const [preview, setPreview] = useState<SpreadsheetPreview | null>(null);
  const [batch, setBatch] = useState<EmissionBatch | null>(null);
  const [summary, setSummary] = useState<GenerationSummary | null>(null);
  const [validating, setValidating] = useState(false);
  const [starting, setStarting] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState("");
  const [jobActionBusy, setJobActionBusy] = useState(false);
  const [driveConnected, setDriveConnected] = useState(false);
  const [driveAccount, setDriveAccount] = useState<string | null>(null);
  const [storageProvider, setStorageProvider] = useState<"google_drive" | "local">("google_drive");
  const [driveLoading, setDriveLoading] = useState(true);
  const [connectingDrive, setConnectingDrive] = useState(false);
  const [selectingEvent, setSelectingEvent] = useState<string | null>(null);
  const [folderChoices, setFolderChoices] = useState<Record<string, FolderChoice>>({});
  const [disconnectingDrive, setDisconnectingDrive] = useState(false);
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const startLockRef = useRef(false);

  const loadDriveStatus = useCallback(async () => {
    setDriveLoading(true);
    try {
      const status = await getGoogleDriveStatus();
      setDriveConnected(status.connected);
      setDriveAccount(status.account_email);
      setStorageProvider(status.storage_provider ?? "google_drive");
      if (!status.connected) setFolderChoices({});
    } catch (requestError) {
      setDriveConnected(false);
      setDriveAccount(null);
      setError(failureMessage(requestError, "Não foi possível consultar o Google Drive."));
    } finally {
      setDriveLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    const params = new URLSearchParams(window.location.search);
    const oauthStatus = params.get("google_drive");
    if (oauthStatus) {
      window.history.replaceState({}, "", window.location.pathname);
      if (oauthStatus === "error") {
        setError("A conexão com o Google Drive não foi concluída.");
      }
    }
    queueMicrotask(() => {
      if (!cancelled) void loadDriveStatus();
    });
    return () => {
      cancelled = true;
    };
  }, [loadDriveStatus]);

  const handleConnectDrive = async () => {
    if (connectingDrive) return;
    setConnectingDrive(true);
    setError("");
    try {
      const authorizationUrl = await startGoogleDriveOAuth();
      window.location.assign(authorizationUrl);
    } catch (requestError) {
      setError(failureMessage(requestError, "Não foi possível iniciar o login do Google."));
      setConnectingDrive(false);
    }
  };

  const handleSelectFolder = async (eventKey: string) => {
    if (selectingEvent !== null) return;
    setSelectingEvent(eventKey);
    setError("");
    try {
      const session = await getGoogleDrivePickerSession();
      const selected = await pickGoogleDriveFolder(session);
      if (!selected) return;
      const validated = await selectGoogleDriveFolder(selected.id, eventKey);
      setFolderChoices((current) => ({
        ...current,
        [eventKey]: { folderId: selected.id, folderName: validated.folder_name },
      }));
    } catch (requestError) {
      setError(failureMessage(requestError, "Não foi possível validar a pasta selecionada."));
      if ((requestError as { response?: { status?: number } })?.response?.status === 401) {
        setDriveConnected(false);
        setDriveAccount(null);
        setFolderChoices({});
      }
    } finally {
      setSelectingEvent(null);
    }
  };

  const handleDisconnectDrive = async () => {
    setDisconnectingDrive(true);
    setError("");
    try {
      await disconnectGoogleDrive();
      setDriveConnected(false);
      setDriveAccount(null);
      setFolderChoices({});
      setConfirmDisconnect(false);
    } catch (requestError) {
      setError(failureMessage(requestError, "Não foi possível desconectar o Google Drive."));
    } finally {
      setDisconnectingDrive(false);
    }
  };

  const acceptBatch = useCallback((next: EmissionBatch) => {
    setBatch(next);
    if (["completed", "partial", "cancelled"].includes(next.status)) {
      setSummary(next.result ?? fallbackSummary(next));
      setStep("done");
    } else {
      setStep("progress");
      if (next.status === "failed") {
        setError(next.error_message || "A emissão foi interrompida.");
      }
    }
  }, []);

  const handleCancel = async () => {
    if (!batch || jobActionBusy) return;
    setJobActionBusy(true);
    setError("");
    try {
      acceptBatch(await cancelEmissionBatch(batch.id));
    } catch (requestError) {
      setError(failureMessage(requestError, "Não foi possível cancelar o lote."));
    } finally {
      setJobActionBusy(false);
    }
  };

  const handleRetry = async () => {
    if (!batch || jobActionBusy) return;
    setJobActionBusy(true);
    setError("");
    try {
      acceptBatch(await retryEmissionBatch(batch.id));
    } catch (requestError) {
      setError(failureMessage(requestError, "Não foi possível retomar o lote."));
    } finally {
      setJobActionBusy(false);
    }
  };

  /* Resume a submitted batch after refresh. The spreadsheet itself and its
   * participant data are never persisted in browser storage. */
  useEffect(() => {
    const raw = localStorage.getItem(storageKey);
    if (!raw) return;
    let stored: StoredBatch;
    try {
      stored = JSON.parse(raw) as StoredBatch;
    } catch {
      localStorage.removeItem(storageKey);
      return;
    }
    if (!stored.idempotencyKey) {
      localStorage.removeItem(storageKey);
      return;
    }
    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) return;
      const request = stored.batchId
        ? getEmissionBatch(stored.batchId)
        : resumeEmissionBatch(stored.idempotencyKey);
      request
        .then((restored) => {
          if (cancelled) return;
          localStorage.setItem(
            storageKey,
            JSON.stringify({ idempotencyKey: stored.idempotencyKey, batchId: restored.id }),
          );
          acceptBatch(restored);
        })
        .catch(() => {
          if (!cancelled) localStorage.removeItem(storageKey);
        });
    });
    return () => {
      cancelled = true;
    };
  }, [acceptBatch, storageKey]);

  useEffect(() => {
    if (!batch || !["queued", "processing"].includes(batch.status)) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const next = await getEmissionBatch(batch.id);
        if (!cancelled) acceptBatch(next);
      } catch (requestError) {
        if (!cancelled) {
          setError(
            failureMessage(
              requestError,
              "Não foi possível atualizar o progresso. Tentaremos novamente.",
            ),
          );
        }
      }
    };
    const timer = window.setInterval(poll, 1200);
    queueMicrotask(() => {
      if (!cancelled) void poll();
    });
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [acceptBatch, batch?.id, batch?.status]);

  const reset = () => {
    localStorage.removeItem(storageKey);
    startLockRef.current = false;
    setStep("upload");
    setFile(null);
    setDataEmissao("");
    setCertificateType("");
    setCertificateTypeError("");
    setTextoPadrao(DEFAULT_BODY_TEXT);
    setPreview(null);
    setBatch(null);
    setSummary(null);
    setFolderChoices({});
    setError("");
  };

  const perWork = isPerWorkType(certificateType);
  // A resumed batch knows its type even when the form was reset by a reload.
  const summaryType = batch?.certificate_type ?? certificateType;
  const summaryPerWork = isPerWorkType(summaryType);
  // Per-work rows are named by their work, never by the first author alone.
  const workTitleByRow = new Map<number, string | undefined>(
    perWork ? (preview?.valid ?? []).map((row) => [row.row_number, row.titulo_trabalho]) : [],
  );
  const rowLabel = (row: { row_number: number; nome: string }) => {
    const title = workTitleByRow.get(row.row_number);
    return `linha ${row.row_number}: ${title ? `“${title}”` : row.nome}`;
  };
  const hasBodyText = textoPadrao.trim() !== "";
  const canValidate = Boolean(file) && (perWork || hasBodyText);
  const offeredVariables = (bodyVariables.data?.variables ?? []).filter(
    (variable) => !perWork || variable.per_work !== false,
  );

  const changeCertificateType = (next: string) => {
    const untouched = textoPadrao.trim() === DEFAULT_BODY_TEXT;
    if (isPerWorkType(next) && !isPerWorkType(certificateType) && untouched) {
      // The ordinary pre-filled text gives way to the automatic body.
      setTextoPadrao("");
    } else if (!isPerWorkType(next) && isPerWorkType(certificateType) && !hasBodyText) {
      // Ordinary types require a text: offer the usual one again.
      setTextoPadrao(DEFAULT_BODY_TEXT);
    }
    setCertificateType(next);
    setCertificateTypeError("");
  };

  const insertVariable = (token: string) => {
    const element = textareaRef.current;
    const start = element ? element.selectionStart : textoPadrao.length;
    const end = element ? element.selectionEnd : textoPadrao.length;
    const before = textoPadrao.slice(0, start);
    const after = textoPadrao.slice(end);
    // Keep the variable apart from adjacent words: "dias{{x}}" would print glued.
    const spaceBefore = /[\p{L}\p{N}}]$/u.test(before) ? " " : "";
    const spaceAfter = /^[\p{L}\p{N}{]/u.test(after) ? " " : "";
    const inserted = `${spaceBefore}${token}${spaceAfter}`;
    setTextoPadrao(before + inserted + after);
    const caret = start + inserted.length;
    requestAnimationFrame(() => {
      textareaRef.current?.focus();
      textareaRef.current?.setSelectionRange(caret, caret);
    });
  };

  const handleValidate = async () => {
    if (!file || !canValidate || validating) return;
    if (!certificateType) {
      setCertificateTypeError("Selecione o tipo do certificado.");
      return;
    }
    setValidating(true);
    setError("");
    try {
      const result = await validateSpreadsheet(
        file,
        dataEmissao || undefined,
        textoPadrao,
        certificateType,
      );
      setPreview(result);
      setStep("preview");
    } catch (requestError) {
      setError(failureMessage(requestError, "Não foi possível ler a planilha."));
    } finally {
      setValidating(false);
    }
  };

  const handleStart = async () => {
    if (!file || !preview || startLockRef.current) return;
    if (!certificateType) {
      setError("Selecione o tipo do certificado antes de emitir.");
      return;
    }
    startLockRef.current = true;
    setStarting(true);
    setError("");
    let idempotencyKey = createUuid();
    try {
      const stored = JSON.parse(localStorage.getItem(storageKey) || "null") as StoredBatch | null;
      if (stored?.idempotencyKey) idempotencyKey = stored.idempotencyKey;
    } catch {
      // A malformed local record is safely replaced below.
    }
    localStorage.setItem(storageKey, JSON.stringify({ idempotencyKey }));
    try {
      const created = await startEmissionBatch(
        file,
        idempotencyKey,
        certificateType,
        dataEmissao || undefined,
        textoPadrao,
        storageProvider === "local"
          ? {}
          : Object.fromEntries(
              Object.entries(folderChoices).map(([event, choice]) => [event, choice.folderId]),
            ),
      );
      localStorage.setItem(
        storageKey,
        JSON.stringify({ idempotencyKey, batchId: created.id }),
      );
      setConfirming(false);
      acceptBatch(created);
    } catch (requestError) {
      setError(failureMessage(requestError, "Não foi possível iniciar a emissão."));
      startLockRef.current = false;
      setConfirming(false);
    } finally {
      setStarting(false);
    }
  };

  const allDestinationsReady =
    storageProvider === "local" ||
    Boolean(
      preview?.events.length
        && preview.events.every((event) => Boolean(folderChoices[event.key]?.folderId)),
    );
  const stepIndex = STEPS.findIndex((entry) => entry.id === step);

  return (
    <>
      <PageHeader
        title="Emitir certificados"
        description="Valide a planilha, confira as linhas e confirme um lote idempotente."
      />
      <Stepper steps={STEPS} current={stepIndex} className="mb-5" />
      {error && step !== "progress" && (
        <Alert tone="danger" className="mb-4">{error}</Alert>
      )}

      {step === "upload" && (
        <div className="space-y-4">
          <Panel>
            <PanelHeader
              title={storageProvider === "local" ? "Armazenamento" : "Google Drive"}
              description={storageProvider === "local" ? "Os PDFs serão gravados no volume persistente do servidor e incluídos no backup local." : "Conecte a conta da Secretaria. As pastas serão escolhidas depois da conferência dos eventos."}
            />
            <PanelBody>
              {driveLoading ? (
                <div role="status" className="flex items-center gap-2 text-[length:var(--text-sm)] text-[color:var(--ink-muted)]">
                  <Icon name="refresh" size={16} /> Verificando conexão com o Google Drive…
                </div>
              ) : driveConnected ? (
                <div className="rounded-[var(--radius)] border border-[color:var(--ok-border)] bg-[var(--ok-bg)] p-4">
                  <p className="font-semibold text-[color:var(--ok-fg)]">✓ {storageProvider === "local" ? "Armazenamento local disponível" : "Conta conectada"}</p>
                  {driveAccount && (
                    <p className="mt-1 text-[length:var(--text-sm)] text-[color:var(--ink)]">{driveAccount}</p>
                  )}
                </div>
              ) : (
                <div className="flex flex-col gap-3 rounded-[var(--radius)] border border-[color:var(--warn-border)] bg-[var(--warn-bg)] p-4 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <p className="font-semibold text-[color:var(--warn-fg)]">Google Drive não conectado</p>
                    <p className="mt-1 text-[length:var(--text-sm)] text-[color:var(--ink-muted)]">
                      A autenticação ocorre na tela oficial do Google.
                    </p>
                  </div>
                  <Button
                    variant="primary"
                    onClick={handleConnectDrive}
                    loading={connectingDrive}
                  >
                    Conectar Google Drive
                  </Button>
                </div>
              )}
            </PanelBody>
          </Panel>
          <Panel>
            <PanelHeader
              title="1. Planilha do lote"
              description={
                perWork
                  ? `Um certificado por trabalho, válido para todos os autores. Colunas obrigatórias: autor1, evento e titulo_trabalho; use autor1 a autor${MAX_WORK_AUTHORS} (colunas vazias são ignoradas). Equipe, carga_horaria e datas são opcionais.`
                  : "Colunas obrigatórias: nome e carga_horaria. Curso, evento, datas, e-mail, Registro Acadêmico (RA), equipe e titulo_trabalho são opcionais."
              }
              actions={
                <AnchorButton
                  href={spreadsheetTemplateUrlFor(certificateType)}
                  download="modelo-certificados.xlsx"
                  variant="secondary"
                  size="sm"
                  icon="spreadsheet"
                >
                  Baixar planilha modelo
                </AnchorButton>
              }
            />
            <PanelBody className="space-y-4">
              <FileDrop file={file} onFile={setFile} />
              <Field
                label="Tipo do certificado"
                required
                error={certificateTypeError || undefined}
                className="max-w-xl"
              >
                {(props) => (
                  <Select
                    {...props}
                    value={certificateType}
                    onChange={(event) => changeCertificateType(event.target.value)}
                  >
                    <option value="">Selecione o tipo do certificado</option>
                    {CERTIFICATE_TYPES.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
              <Field
                label="Data de emissão padrão"
                hint="Opcional; usada apenas onde a linha não tiver data própria."
                className="max-w-xs"
              >
                {(props) => (
                  <TextInput
                    {...props}
                    value={dataEmissao}
                    placeholder="10/06/2026"
                    inputMode="numeric"
                    onChange={(event) => setDataEmissao(event.target.value)}
                  />
                )}
              </Field>
            </PanelBody>
          </Panel>

          <Panel>
            <PanelHeader
              title="2. Texto do certificado"
              description="Os dados institucionais, assinatura, QR Code e código vêm das configurações e do template ativo."
            />
            <PanelBody className="space-y-3">
              <Field
                label="Texto padrão do certificado"
                required={!perWork}
                hint={
                  perWork ? (
                    <>
                      Opcional. Em branco, vale o texto automático
                      {bodyVariables.data?.per_work_automatic_text ? (
                        <>
                          : <q>{bodyVariables.data.per_work_automatic_text}</q> A carga
                          horária só aparece quando preenchida.
                        </>
                      ) : (
                        ", que cita o título do trabalho, o evento e a carga horária quando preenchida."
                      )}{" "}
                      Sem nome: os autores saem no bloco Autores do template.
                    </>
                  ) : undefined
                }
              >
                {(props) => (
                  <Textarea
                    {...props}
                    ref={textareaRef}
                    value={textoPadrao}
                    rows={5}
                    aria-label="Texto padrão do certificado"
                    onChange={(event) => setTextoPadrao(event.target.value)}
                  />
                )}
              </Field>
              {perWork && hasBodyText && (
                <Alert tone="warn" live={false}>
                  Este texto será impresso no lugar do texto automático de{" "}
                  {certificateTypeLabel(certificateType)}. Confira se ele fala do trabalho
                  e não de um participante; para usar o texto automático, apague o campo.
                </Alert>
              )}
              <div className="rounded-[var(--radius)] border border-[color:var(--line)] bg-[var(--surface-sunken)] p-3">
                <p className="mb-2 text-[length:var(--text-xs)] text-[color:var(--ink-muted)]">
                  Inserir variável na posição do cursor:
                </p>
                {bodyVariables.error && (
                  <div className="flex flex-wrap items-center gap-2 text-[length:var(--text-xs)] text-[color:var(--ink-muted)]">
                    <span role="status">
                      Não foi possível carregar as variáveis. Você ainda pode digitá-las no
                      formato <code>{"{{variavel}}"}</code>.
                    </span>
                    <Button size="sm" variant="ghost" icon="refresh" onClick={bodyVariables.reload}>
                      Tentar novamente
                    </Button>
                  </div>
                )}
                {bodyVariables.initialLoading && (
                  <p className="text-[length:var(--text-xs)] text-[color:var(--ink-muted)]">
                    Carregando variáveis…
                  </p>
                )}
                <div className="flex flex-wrap gap-2">
                  {offeredVariables.map(({ token, label }) => (
                    <button
                      key={token}
                      type="button"
                      onClick={() => insertVariable(token)}
                      aria-label={`Inserir ${token}`}
                      className={cn(
                        "inline-flex items-center gap-1.5 rounded-[var(--radius)] border px-2.5 py-1.5",
                        "border-[color:var(--line-strong)] bg-[var(--surface)] text-[length:var(--text-xs)] font-medium",
                        "hover:border-[color:var(--brand-500)] hover:bg-[var(--brand-50)]",
                      )}
                    >
                      <Icon name="plus" size={13} />{label}
                      <code>{token}</code>
                    </button>
                  ))}
                </div>
              </div>
            </PanelBody>
          </Panel>
          <div className="flex justify-end">
            <Button
              variant="primary"
              size="lg"
              iconAfter="arrow-right"
              onClick={handleValidate}
              disabled={!canValidate}
              loading={validating}
            >
              {validating ? "Validando planilha…" : "Validar planilha"}
            </Button>
          </div>
        </div>
      )}

      {step === "preview" && preview && (
        <div className="space-y-4">
          <Panel>
            <PanelHeader title="Conferência do lote" />
            <PanelBody>
              <dl className="grid gap-3 sm:grid-cols-3">
                <SummaryFigure label="Linhas na planilha" value={preview.total} />
                <SummaryFigure label="Aptas para emissão" value={preview.valid_count} tone={preview.valid_count ? "ok" : "neutral"} />
                <SummaryFigure label="Com erro" value={preview.invalid_count} tone={preview.invalid_count ? "danger" : "neutral"} />
              </dl>
              <p className="mt-4 text-[length:var(--text-sm)] text-[color:var(--ink-muted)]">
                Tipo do certificado: <strong className="text-[color:var(--ink)]">{certificateTypeLabel(certificateType)}</strong>
              </p>
            </PanelBody>
          </Panel>

          {preview.resolved_text_preview && (
            <Panel>
              <PanelHeader
                title="Prévia do texto gerado"
                description={
                  perWork && !hasBodyText
                    ? "Texto automático, resolvido para a primeira linha válida."
                    : "Variáveis resolvidas para a primeira linha válida."
                }
              />
              <PanelBody><p className="certificate-text whitespace-pre-wrap">{preview.resolved_text_preview}</p></PanelBody>
            </Panel>
          )}

          {preview.warnings && preview.warnings.length > 0 && (
            <Alert tone="warn" title="Avisos da planilha" live={false}>
              <ul className="list-disc space-y-1 pl-5">
                {preview.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </Alert>
          )}

          {preview.template_problem && (
            <Alert tone="danger" title="Não é possível confirmar este lote" live={false}>
              <p>{preview.template_problem}</p>
              {preview.can_manage_templates && (
                <LinkButton to="/template" size="sm" className="mt-2">
                  Abrir Template
                </LinkButton>
              )}
            </Alert>
          )}

          {preview.missing_settings && preview.missing_settings.length > 0 && (
            <Alert tone="danger" title="Não é possível confirmar este lote" live={false}>
              <p>{preview.missing_settings_message}</p>
              {preview.can_manage_settings && (
                <LinkButton to="/configuracoes" size="sm" className="mt-2">
                  Abrir Configurações
                </LinkButton>
              )}
            </Alert>
          )}

          {preview.empty_fields && preview.empty_fields.length > 0 && (
            <Alert tone="warn" title="Campos do template em branco em algumas linhas" live={false}>
              <p>Os certificados dessas linhas serão gerados sem o campo indicado.</p>
              <ul className="mt-2 space-y-1.5">
                {preview.empty_fields.map((field) => (
                  <li key={field.key}>
                    <strong>{field.label}</strong>: {field.row_count} linha(s) —{" "}
                    {field.rows.map(rowLabel).join("; ")}
                    {field.row_count > field.rows.length ? "; …" : ""}
                    {field.truncated &&
                      ` Verificadas apenas as primeiras ${field.checked_rows} linhas válidas.`}
                  </li>
                ))}
              </ul>
            </Alert>
          )}

          {preview.layout_warnings && preview.layout_warnings.length > 0 && (
            <Alert tone="warn" title="Textos que não cabem na caixa do template" live={false}>
              <p>
                Os certificados serão gerados sem cortar o texto, mas ele pode
                ultrapassar a área reservada. Se preferir, ajuste a caixa ou a fonte
                no template, ou encurte o texto, antes de confirmar.
              </p>
              <ul className="mt-2 space-y-1.5">
                {preview.layout_warnings.map((warning) => (
                  <li key={warning.key}>
                    <strong>{warning.label}</strong> (caixa de {warning.height} px):{" "}
                    {warning.applies_to_all
                      ? "texto fixo do template; vale para todos os certificados."
                      : `${warning.row_count} ${perWork ? "trabalho(s)" : "participante(s)"} — ${warning.rows
                          .map(rowLabel)
                          .join("; ")}${warning.row_count > warning.rows.length ? "; …" : ""}`}
                    {warning.truncated &&
                      ` Verificadas apenas as primeiras ${warning.checked_rows} linhas válidas.`}
                  </li>
                ))}
              </ul>
            </Alert>
          )}

          {preview.invalid_count > 0 && (
            <Panel>
              <PanelHeader
                title={`Linhas inválidas (${preview.invalid_count})`}
                description="Não serão emitidas neste lote. O relatório não inclui Registro Acadêmico (RA) nem e-mail."
                actions={
                  <Button size="sm" icon="download" onClick={() => exportInvalidRows(preview)}>
                    Exportar erros
                  </Button>
                }
              />
              <TableScroll label="Linhas com erro" className="rounded-none border-0 border-t">
                <Table caption="Linhas rejeitadas e os motivos">
                  <Thead><Tr><Th>Linha</Th><Th>Problema encontrado</Th></Tr></Thead>
                  <Tbody>
                    {preview.invalid.slice(0, 100).map((row) => (
                      <Tr key={row.row_number}>
                        <TdHeader>{row.row_number}</TdHeader>
                        <Td className="text-[color:var(--danger-fg)]">{row.errors.join("; ")}</Td>
                      </Tr>
                    ))}
                  </Tbody>
                </Table>
              </TableScroll>
            </Panel>
          )}

          {preview.valid_count > 0 ? (
            <Panel>
              <PanelHeader
                title={`Linhas válidas (${preview.valid_count})`}
                description={preview.valid.length > 50 ? "Mostrando as 50 primeiras." : undefined}
              />
              <TableScroll label="Linhas válidas" className="rounded-none border-0 border-t">
                {perWork ? (
                  <WorkRowsTable rows={preview.valid.slice(0, 50)} />
                ) : (
                  <Table caption="Participantes aptos para emissão">
                    <Thead><Tr><Th>Linha</Th><Th>Participante</Th><Th className="hidden md:table-cell">Curso/evento</Th><Th>Carga</Th><Th>Emissão</Th></Tr></Thead>
                    <Tbody>
                      {preview.valid.slice(0, 50).map((row) => (
                        <Tr key={row.row_number}>
                          <Td>{row.row_number}</Td>
                          <TdHeader>
                            {row.autores && row.autores.length > 1 ? (
                              <span title={row.autores.join(", ")}>
                                {row.nome}{" "}
                                <span className="text-[color:var(--ink-muted)]">
                                  +{row.autores.length - 1} autor(es)
                                </span>
                              </span>
                            ) : (
                              row.nome
                            )}
                          </TdHeader>
                          <Td className="hidden text-[color:var(--ink-muted)] md:table-cell">{row.titulo_trabalho || row.evento || row.curso || "—"}</Td>
                          <Td>{row.carga_horaria == null ? "—" : `${row.carga_horaria}h`}</Td>
                          <Td>{row.data_emissao}</Td>
                        </Tr>
                      ))}
                    </Tbody>
                  </Table>
                )}
              </TableScroll>
            </Panel>
          ) : (
            <Alert tone="warn" title="Nenhuma linha pode ser emitida">
              Corrija os erros e valide uma nova planilha.
            </Alert>
          )}

          <Panel>
            <PanelBody className="flex flex-col-reverse gap-2 sm:flex-row sm:items-center sm:justify-between">
              <Button variant="secondary" icon="chevron-left" onClick={reset}>Trocar arquivo</Button>
              <div className="flex flex-col items-end gap-2">
                <p className="text-[length:var(--text-xs)] text-[color:var(--ink-muted)]">
                  A confirmação cria um lote auditável e idempotente.
                </p>
                <Button
                  variant="primary"
                  size="lg"
                  icon="certificate"
                  onClick={() => setStep("destination")}
                  disabled={
                    preview.valid_count === 0 ||
                    startLockRef.current ||
                    Boolean(preview.template_problem) ||
                    (preview.missing_settings?.length ?? 0) > 0
                  }
                >
                  Definir destino no Google Drive
                </Button>
              </div>
            </PanelBody>
          </Panel>
        </div>
      )}

      {step === "destination" && preview && (
        <div className="space-y-4">
          <Panel>
            <PanelHeader
              title="Destino dos certificados"
              description={storageProvider === "local" ? "Os PDFs serão guardados no volume persistente local do servidor." : "Cada evento recebe uma pasta exclusiva. A escolha fica congelada no lote após a confirmação."}
              actions={storageProvider !== "local" && driveConnected ? (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setConfirmDisconnect(true)}
                >
                  Desconectar Google Drive
                </Button>
              ) : undefined}
            />
            <PanelBody className="space-y-4">
              {driveLoading ? (
                <div role="status" className="flex items-center gap-2 text-[length:var(--text-sm)] text-[color:var(--ink-muted)]">
                  <Icon name="refresh" size={16} /> Verificando conexão com o Google Drive…
                </div>
              ) : driveConnected ? (
                <div className="rounded-[var(--radius)] border border-[color:var(--ok-border)] bg-[var(--ok-bg)] p-4">
                  <p className="font-semibold text-[color:var(--ok-fg)]">✓ {storageProvider === "local" ? "Armazenamento local disponível" : "Conta conectada"}</p>
                  {driveAccount && (
                    <p className="mt-1 text-[length:var(--text-sm)] text-[color:var(--ink)]">{driveAccount}</p>
                  )}
                </div>
              ) : (
                <div className="rounded-[var(--radius)] border border-[color:var(--warn-border)] bg-[var(--warn-bg)] p-4">
                  <p className="font-semibold text-[color:var(--warn-fg)]">Google Drive não conectado</p>
                  <p className="mt-1 text-[length:var(--text-sm)] text-[color:var(--ink-muted)]">
                    Entre com a conta Google da Secretaria para escolher as pastas oficiais.
                  </p>
                  <Button
                    className="mt-3"
                    variant="primary"
                    onClick={handleConnectDrive}
                    loading={connectingDrive}
                  >
                    Conectar Google Drive
                  </Button>
                </div>
              )}
            </PanelBody>
          </Panel>

          {storageProvider !== "local" && driveConnected && preview.events.map((event) => {
            const selected = folderChoices[event.key];
            const busy = selectingEvent === event.key;
            return (
              <Panel key={event.key || "__sem_evento__"}>
                <PanelHeader
                  title={event.label}
                  description={`${event.count} certificado(s) neste grupo`}
                />
                <PanelBody>
                  {selected ? (
                    <div className="flex flex-col gap-3 rounded-[var(--radius)] border border-[color:var(--ok-border)] bg-[var(--ok-bg)] p-4 sm:flex-row sm:items-center sm:justify-between">
                      <div>
                        <p className="text-[length:var(--text-xs)] font-medium uppercase tracking-wide text-[color:var(--ink-muted)]">Pasta selecionada</p>
                        <p className="mt-1 flex items-center gap-2 font-semibold text-[color:var(--ink)]">
                          <Icon name="folder" size={17} /> {selected.folderName}
                        </p>
                        <p className="mt-1 text-[length:var(--text-sm)] text-[color:var(--ok-fg)]">✓ Pasta pronta para receber os certificados</p>
                      </div>
                      <Button
                        variant="secondary"
                        onClick={() => handleSelectFolder(event.key)}
                        loading={busy}
                        disabled={selectingEvent !== null && !busy}
                      >
                        Trocar pasta
                      </Button>
                    </div>
                  ) : (
                    <div className="flex flex-col gap-3 rounded-[var(--radius)] border border-[color:var(--warn-border)] bg-[var(--warn-bg)] p-4 sm:flex-row sm:items-center sm:justify-between">
                      <div>
                        <p className="font-medium text-[color:var(--warn-fg)]">Selecione uma pasta para continuar</p>
                        <p className="mt-1 text-[length:var(--text-sm)] text-[color:var(--ink-muted)]">
                          Os PDFs deste evento não serão misturados com outros eventos.
                        </p>
                      </div>
                      <Button
                        variant="primary"
                        onClick={() => handleSelectFolder(event.key)}
                        loading={busy}
                        disabled={selectingEvent !== null && !busy}
                      >
                        Selecionar pasta no Google Drive
                      </Button>
                    </div>
                  )}
                </PanelBody>
              </Panel>
            );
          })}

          <Panel>
            <PanelBody className="flex flex-col-reverse gap-2 sm:flex-row sm:items-center sm:justify-between">
              <Button variant="secondary" icon="chevron-left" onClick={() => setStep("preview")}>
                Voltar à conferência
              </Button>
              <Button
                variant="primary"
                size="lg"
                icon="certificate"
                onClick={() => setConfirming(true)}
                disabled={!driveConnected || !allDestinationsReady || startLockRef.current}
              >
                Confirmar emissão de {preview.valid_count} certificado(s)
              </Button>
            </PanelBody>
          </Panel>
          {!allDestinationsReady && driveConnected && (
            <Alert tone="warn">
              Selecione uma pasta do Google Drive para todos os eventos antes de emitir os certificados.
            </Alert>
          )}
        </div>
      )}

      {step === "progress" && batch && (
        <div className="space-y-4">
          <Alert
            tone={batch.status === "failed" ? "danger" : "info"}
            title={batch.status === "failed" ? "Emissão interrompida" : "Emissão em andamento"}
          >
            {batch.status === "failed"
              ? batch.error_message || "Tente uma nova emissão."
              : "O progresso é persistente. Você pode atualizar ou fechar esta página e continuar depois."}
          </Alert>
          <Panel>
            <PanelHeader title={`Lote ${batch.id}`} description={`Estado: ${batch.status}`} />
            <PanelBody className="space-y-4">
              <p className="text-[length:var(--text-sm)] text-[color:var(--ink-muted)]">
                Tipo do certificado: <strong className="text-[color:var(--ink)]">
                  {certificateTypeLabel(batch.certificate_type, batch.certificate_type_label)}
                </strong>
              </p>
              <div>
                <div className="mb-1 flex justify-between text-[length:var(--text-sm)]">
                  <span>{batch.processed_count} de {batch.valid_count} linhas válidas processadas</span>
                  <strong>{batch.progress_percent}%</strong>
                </div>
                <progress
                  value={batch.progress_percent}
                  max={100}
                  aria-label="Progresso real da emissão"
                  className="h-3 w-full"
                />
              </div>
              <dl className="grid gap-3 sm:grid-cols-4">
                <SummaryFigure label="Gerados" value={batch.generated_count} tone="ok" />
                <SummaryFigure label="Duplicados" value={batch.duplicate_count} tone="warn" />
                <SummaryFigure label="Inválidos" value={batch.invalid_count} tone={batch.invalid_count ? "danger" : "neutral"} />
                <SummaryFigure label="Falhos" value={batch.failed_count} tone={batch.failed_count ? "danger" : "neutral"} />
              </dl>
              <div className="flex flex-wrap gap-2">
                {["queued", "processing"].includes(batch.status) && (
                  <Button variant="danger" onClick={handleCancel} loading={jobActionBusy}>
                    Cancelar lote
                  </Button>
                )}
                {batch.status === "failed" && (batch.attempt_count ?? 0) < (batch.max_attempts ?? 3) && (
                  <Button variant="primary" onClick={handleRetry} loading={jobActionBusy}>
                    Retomar lote
                  </Button>
                )}
                {batch.status === "failed" && (
                  <Button variant="secondary" icon="issue" onClick={reset}>Iniciar nova emissão</Button>
                )}
              </div>
            </PanelBody>
          </Panel>
        </div>
      )}

      {step === "done" && summary && (
        <div className="space-y-4">
          <Alert
            tone={summary.failed_count || summary.invalid_count ? "warn" : "ok"}
            title="Lote concluído"
          >
            O resultado foi persistido e pode ser consultado pelo histórico do lote.
          </Alert>
          <Panel>
            <PanelHeader title="Resumo final" description={summary.batch_id ? `Lote ${summary.batch_id}` : undefined} />
            <PanelBody className="space-y-4">
              {batch && (
                <p className="text-[length:var(--text-sm)] text-[color:var(--ink-muted)]">
                  Tipo do certificado: <strong className="text-[color:var(--ink)]">
                    {certificateTypeLabel(batch.certificate_type, batch.certificate_type_label)}
                  </strong>
                </p>
              )}
              <dl className="grid gap-3 sm:grid-cols-4">
                <SummaryFigure label="Gerados" value={summary.generated_count} tone={summary.generated_count ? "ok" : "neutral"} />
                <SummaryFigure label="Duplicados" value={summary.duplicate_count} tone={summary.duplicate_count ? "warn" : "neutral"} />
                <SummaryFigure label="Inválidos" value={summary.invalid_count} tone={summary.invalid_count ? "danger" : "neutral"} />
                <SummaryFigure label="Falhos" value={summary.failed_count} tone={summary.failed_count ? "danger" : "neutral"} />
              </dl>
            </PanelBody>
          </Panel>

          {summary.generated.length > 0 && (
            <ResultTable
              title={`Certificados gerados (${summary.generated_count})`}
              headers={[summaryPerWork ? "Trabalho" : "Participante", "Código"]}
              rows={summary.generated.map((item) => [
                <SummarySubject item={item} certificateType={summaryType} />,
                item.code,
              ])}
            />
          )}
          {summary.duplicates.length > 0 && (
            <ResultTable
              title={`Duplicados mantidos (${summary.duplicate_count})`}
              headers={[summaryPerWork ? "Trabalho" : "Participante", "Código existente"]}
              rows={summary.duplicates.map((item) => [
                <SummarySubject item={item} certificateType={summaryType} />,
                item.existing_code,
              ])}
            />
          )}
          {summary.failed.length > 0 && (
            <ResultTable
              title={`Falhas (${summary.failed_count})`}
              headers={[summaryPerWork ? "Linha e primeiro autor" : "Participante", "Motivo"]}
              // A failed row has no certificate to read the work back from.
              rows={summary.failed.map((item) => [
                summaryPerWork && item.row_number
                  ? `Linha ${item.row_number} — ${item.name}`
                  : item.name,
                item.error,
              ])}
              danger
            />
          )}
          <div className="flex flex-wrap gap-2">
            {summary.batch_id && (
              <LinkButton
                to={`/historico?batch_id=${encodeURIComponent(summary.batch_id)}`}
                variant="primary"
                icon="history"
              >
                Abrir histórico deste lote
              </LinkButton>
            )}
            <Button variant="secondary" icon="issue" onClick={reset}>Emitir outra planilha</Button>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={confirming}
        title="Confirmar emissão do lote"
        description="Confira a quantidade antes de iniciar."
        confirmLabel={`Emitir ${preview?.valid_count ?? 0} certificado(s)`}
        tone="primary"
        busy={starting}
        error={error}
        onConfirm={handleStart}
        onClose={() => { if (!starting) setConfirming(false); }}
      >
        <p className="text-[length:var(--text-sm)] text-[color:var(--ink)]">
          Serão processadas <strong>{preview?.valid_count ?? 0} linhas válidas</strong>.
          {preview?.invalid_count ? ` ${preview.invalid_count} linha(s) inválida(s) permanecerão no relatório.` : ""}
        </p>
        <p className="mt-2 text-[length:var(--text-sm)] text-[color:var(--ink)]">
          Tipo congelado no lote: <strong>{certificateTypeLabel(certificateType)}</strong>.
        </p>
      </ConfirmDialog>
      <ConfirmDialog
        open={confirmDisconnect}
        title="Desconectar Google Drive"
        description="A desconexão impede novas emissões até que uma conta seja conectada novamente."
        confirmLabel="Desconectar"
        tone="danger"
        busy={disconnectingDrive}
        onConfirm={handleDisconnectDrive}
        onClose={() => { if (!disconnectingDrive) setConfirmDisconnect(false); }}
      >
        <p className="text-[length:var(--text-sm)] text-[color:var(--ink)]">
          Certificados existentes e seus PDFs não serão apagados nem alterados.
        </p>
      </ConfirmDialog>
    </>
  );
}

function SummarySubject({
  item,
  certificateType,
}: {
  item: GenerationSummary["generated"][number] | GenerationSummary["duplicates"][number];
  certificateType: string | null | undefined;
}) {
  return (
    <CertificateSubject
      source={{
        participant_name: item.name,
        certificate_type: certificateType,
        work_title: item.work_title,
        authors: item.authors,
      }}
    />
  );
}

function ResultTable({
  title,
  headers,
  rows,
  danger = false,
}: {
  title: string;
  headers: [string, string];
  rows: [ReactNode, string][];
  danger?: boolean;
}) {
  return (
    <Panel>
      <PanelHeader title={title} />
      <TableScroll label={title} className="rounded-none border-0 border-t">
        <Table caption={title}>
          <Thead><Tr><Th>{headers[0]}</Th><Th>{headers[1]}</Th></Tr></Thead>
          <Tbody>{rows.map((row, index) => (
            <Tr key={`${row[1]}-${index}`}>
              <TdHeader>{row[0]}</TdHeader>
              <Td className={danger ? "text-[color:var(--danger-fg)]" : undefined}>{row[1]}</Td>
            </Tr>
          ))}</Tbody>
        </Table>
      </TableScroll>
    </Panel>
  );
}

function SummaryFigure({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: number;
  tone?: "neutral" | "ok" | "warn" | "danger";
}) {
  const toneClass = {
    neutral: "text-[color:var(--ink)]",
    ok: "text-[color:var(--ok-fg)]",
    warn: "text-[color:var(--warn-fg)]",
    danger: "text-[color:var(--danger-fg)]",
  }[tone];
  return (
    <div className="rounded-[var(--radius)] border border-[color:var(--line)] bg-[var(--surface-sunken)] px-4 py-3">
      <dt className="text-[length:var(--text-xs)] font-medium text-[color:var(--ink-muted)]">{label}</dt>
      <dd className={cn("mt-0.5 text-[length:var(--text-2xl)] font-semibold tabular-nums", toneClass)}>
        {value.toLocaleString("pt-BR")}
      </dd>
    </div>
  );
}

function FileDrop({ file, onFile }: { file: File | null; onFile: (file: File | null) => void }) {
  const [dragging, setDragging] = useState(false);
  const [fileError, setFileError] = useState("");

  const accept = (next: File | null) => {
    if (next && !next.name.toLowerCase().endsWith(".xlsx")) {
      setFileError("Selecione um arquivo no formato .xlsx.");
      onFile(null);
      return;
    }
    setFileError("");
    onFile(next);
  };

  return (
    <div>
      <div
        onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          accept(event.dataTransfer.files?.[0] ?? null);
        }}
        className={cn(
          "flex flex-col items-center gap-2 rounded-[var(--radius-md)] border border-dashed px-4 py-6 text-center",
          dragging ? "border-[color:var(--brand-500)] bg-[var(--brand-50)]" : "border-[color:var(--line-strong)] bg-[var(--surface-sunken)]",
        )}
      >
        <Icon name="upload" size={22} className="text-[color:var(--ink-muted)]" />
        <p className="text-[length:var(--text-sm)] text-[color:var(--ink-muted)]">Arraste a planilha aqui ou</p>
        <label
          htmlFor="spreadsheet-upload"
          className={cn(
            "inline-flex h-10 cursor-pointer items-center rounded-[var(--radius)] border px-3.5",
            "border-[color:var(--brand-700)] bg-[var(--brand-700)] font-medium text-[color:var(--ink-inverse)]",
            "has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2",
          )}
        >
          Escolher arquivo
          <input
            id="spreadsheet-upload"
            type="file"
            accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            className="sr-only"
            onChange={(event) => accept(event.target.files?.[0] ?? null)}
          />
        </label>
        <p className="text-[length:var(--text-xs)] text-[color:var(--ink-subtle)]">Formato .xlsx</p>
      </div>
      {fileError && <Alert tone="danger" className="mt-2">{fileError}</Alert>}
      <p role="status" aria-live="polite" className="mt-2 flex items-center gap-2 text-[length:var(--text-sm)]">
        {file ? (
          <>
            <Icon name="spreadsheet" size={16} className="text-[color:var(--ok-fg)]" />
            <span className="min-w-0 truncate font-medium">{file.name}</span>
            <button type="button" onClick={() => accept(null)} className="ml-auto text-[length:var(--text-xs)] underline">Remover</button>
          </>
        ) : <span className="text-[color:var(--ink-subtle)]">Nenhum arquivo selecionado</span>}
      </p>
    </div>
  );
}
