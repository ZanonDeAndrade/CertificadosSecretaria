import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import EmitirCertificados from "./EmitirCertificados";
import { renderWithProviders } from "../test/renderWithProviders";
import {
  disconnectGoogleDrive,
  getGoogleDrivePickerSession,
  getGoogleDriveStatus,
  resumeEmissionBatch,
  selectGoogleDriveFolder,
  startEmissionBatch,
  startGoogleDriveOAuth,
  validateSpreadsheet,
} from "../services/api";
import { pickGoogleDriveFolder } from "../lib/googlePicker";

vi.mock("../services/api", () => ({
  spreadsheetTemplateUrl: "http://test/certificates/spreadsheet-template",
  validateSpreadsheet: vi.fn(),
  startEmissionBatch: vi.fn(),
  getEmissionBatch: vi.fn(),
  resumeEmissionBatch: vi.fn(),
  getGoogleDriveStatus: vi.fn(),
  startGoogleDriveOAuth: vi.fn(),
  getGoogleDrivePickerSession: vi.fn(),
  selectGoogleDriveFolder: vi.fn(),
  disconnectGoogleDrive: vi.fn(),
  getApiErrorMessage: (_error: unknown, fallback: string) => fallback,
  classifyError: () => "server",
}));

vi.mock("../lib/googlePicker", () => ({
  pickGoogleDriveFolder: vi.fn(),
}));

const PREVIEW = {
  total: 1,
  valid_count: 1,
  invalid_count: 0,
  valid: [
    {
      row_number: 2,
      nome: "Ana",
      curso: "Direito",
      evento: "Semana",
      carga_horaria: 40,
      data_emissao: "10/06/2026",
      data_inicio: "",
      data_fim: "",
    },
  ],
  invalid: [],
  events: [{ key: "Semana", label: "Semana", count: 1 }],
  resolved_text_preview: "participou da Semana, com carga horária de 40 horas.",
};

const SUMMARY = {
  batch_id: "11111111-1111-4111-8111-111111111111",
  generated: [{ name: "Ana", code: "CERT-2026-TESTE" }],
  generated_count: 1,
  duplicates: [],
  duplicate_count: 0,
  failed: [],
  failed_count: 0,
  invalid: [],
  invalid_count: 0,
  total_rows: 1,
};

const COMPLETED_BATCH = {
  id: SUMMARY.batch_id,
  status: "completed" as const,
  total_rows: 1,
  valid_count: 1,
  invalid_count: 0,
  processed_count: 1,
  generated_count: 1,
  duplicate_count: 0,
  failed_count: 0,
  certificate_type: "listener",
  certificate_type_label: "Ouvinte",
  progress_percent: 100,
  result: SUMMARY,
  invalid_report: [],
  error_message: null,
  created_by: 1,
};

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  vi.mocked(validateSpreadsheet).mockResolvedValue(PREVIEW);
  vi.mocked(startEmissionBatch).mockResolvedValue(COMPLETED_BATCH);
  vi.mocked(resumeEmissionBatch).mockResolvedValue(COMPLETED_BATCH);
  vi.mocked(getGoogleDriveStatus).mockResolvedValue({
    connected: true,
    account_email: "secretaria@instituicao.example",
    expires_at: "2026-08-14T18:00:00Z",
  });
  vi.mocked(getGoogleDrivePickerSession).mockResolvedValue({
    access_token: "token-apenas-em-memoria",
    api_key: "picker-key",
    app_id: "123456",
    expires_at: "2026-08-14T18:00:00Z",
  });
  vi.mocked(pickGoogleDriveFolder).mockResolvedValue({
    id: "folder-semana-0001",
    name: "Semana 2026",
  });
  vi.mocked(selectGoogleDriveFolder).mockResolvedValue({
    folder_name: "Semana 2026",
    ready: true,
  });
  vi.mocked(disconnectGoogleDrive).mockResolvedValue();
});

const render = () => renderWithProviders(<EmitirCertificados />);

function textarea(): HTMLTextAreaElement {
  return screen.getByLabelText("Texto padrão do certificado") as HTMLTextAreaElement;
}

function validateButton(): HTMLButtonElement {
  return screen.getByRole("button", { name: /Validar planilha/i }) as HTMLButtonElement;
}

function selectFile(): File {
  const input = document.getElementById("spreadsheet-upload") as HTMLInputElement;
  const file = new File([new Uint8Array([1, 2, 3])], "p.xlsx", {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
  fireEvent.change(input, { target: { files: [file] } });
  return file;
}

async function reachPreview(text = "texto {{nome}}") {
  const file = selectFile();
  fireEvent.change(screen.getByRole("combobox", { name: /Tipo do certificado/i }), {
    target: { value: "listener" },
  });
  fireEvent.change(textarea(), { target: { value: text } });
  fireEvent.click(validateButton());
  await screen.findByText(PREVIEW.resolved_text_preview);
  return file;
}

async function reachDestination(text = "texto {{nome}}") {
  const file = await reachPreview(text);
  fireEvent.click(screen.getByRole("button", { name: /Definir destino no Google Drive/i }));
  await screen.findByText("Destino dos certificados");
  return file;
}

async function chooseFolder() {
  fireEvent.click(
    await screen.findByRole("button", { name: "Selecionar pasta no Google Drive" }),
  );
  await screen.findByText("Semana 2026");
}

test("texto é obrigatório, controla o botão e é enviado ao backend", async () => {
  render();
  expect(textarea().value).toContain("{{carga_horaria}}");
  expect(validateButton().disabled).toBe(true);
  const file = selectFile();
  expect(validateButton().disabled).toBe(false);
  fireEvent.change(textarea(), { target: { value: "   " } });
  expect(validateButton().disabled).toBe(true);
  fireEvent.change(textarea(), { target: { value: "corpo de {{nome}}" } });
  fireEvent.change(screen.getByRole("combobox", { name: /Tipo do certificado/i }), {
    target: { value: "listener" },
  });
  fireEvent.click(validateButton());
  await waitFor(() =>
    expect(validateSpreadsheet).toHaveBeenCalledWith(
      file,
      undefined,
      "corpo de {{nome}}",
      "listener",
    ),
  );
});

test("exige o tipo e oferece todas as opções controladas", async () => {
  render();
  selectFile();
  fireEvent.click(validateButton());
  expect(await screen.findByText("Selecione o tipo do certificado.")).not.toBeNull();
  expect(validateSpreadsheet).not.toHaveBeenCalled();

  const select = screen.getByRole("combobox", {
    name: /Tipo do certificado/i,
  }) as HTMLSelectElement;
  expect(Array.from(select.options).map((option) => option.text)).toEqual([
    "Selecione o tipo do certificado",
    "Ouvinte",
    "Palestrante",
    "Comissão Organizadora",
    "Equipes",
    "Monitoria",
    "Professores participantes de Banca de TCC",
    "Mostra de Iniciação Científica",
  ]);
});

test("exige confirmação e envia texto revisado com uma chave idempotente", async () => {
  const user = userEvent.setup();
  render();
  const file = await reachDestination("texto {{nome}}");
  await chooseFolder();

  await user.click(screen.getByRole("button", { name: /Confirmar emissão de 1/i }));
  expect(screen.getByRole("dialog", { name: "Confirmar emissão do lote" })).not.toBeNull();
  await user.click(screen.getByRole("button", { name: "Emitir 1 certificado(s)" }));

  await waitFor(() => expect(startEmissionBatch).toHaveBeenCalledTimes(1));
  expect(startEmissionBatch).toHaveBeenCalledWith(
    file,
    expect.stringMatching(/^.{16,128}$/),
    "listener",
    undefined,
    "texto {{nome}}",
    { Semana: "folder-semana-0001" },
  );
  expect(await screen.findByText("Resumo final")).not.toBeNull();
  expect(
    screen.getByRole("link", { name: "Abrir histórico deste lote" }).getAttribute("href"),
  ).toBe(`/historico?batch_id=${SUMMARY.batch_id}`);
});

test("retoma lote salvo após atualização sem persistir a planilha", async () => {
  localStorage.setItem(
    "certificados:emission-batch:1",
    JSON.stringify({ idempotencyKey: "batch-key-1234567890" }),
  );
  render();
  expect(await screen.findByText("Resumo final")).not.toBeNull();
  expect(screen.getByText("Ouvinte")).not.toBeNull();
  expect(resumeEmissionBatch).toHaveBeenCalledWith("batch-key-1234567890");
  expect(localStorage.getItem("certificados:emission-batch:1")).not.toContain("Ana");
});

test("limpa o lote ao iniciar outra emissão", async () => {
  const user = userEvent.setup();
  render();
  await reachDestination("corpo editado {{nome}}");
  await chooseFolder();
  await user.click(screen.getByRole("button", { name: /Confirmar emissão de 1/i }));
  await user.click(screen.getByRole("button", { name: "Emitir 1 certificado(s)" }));
  await user.click(await screen.findByRole("button", { name: /Emitir outra planilha/i }));
  expect(textarea().value).toContain("{{carga_horaria}}");
  expect(textarea().value).not.toContain("corpo editado");
  expect(localStorage.getItem("certificados:emission-batch:1")).toBeNull();
});

test("botão insere a variável na posição do cursor", () => {
  render();
  const field = textarea();
  fireEvent.change(field, { target: { value: "AB" } });
  field.focus();
  field.setSelectionRange(1, 1);
  fireEvent.click(screen.getByRole("button", { name: "Inserir {{nome}}" }));
  expect(field.value).toBe("A{{nome}}B");
});

test("mostra estado desconectado e inicia o OAuth sem popup local", async () => {
  vi.mocked(getGoogleDriveStatus).mockResolvedValue({
    connected: false,
    account_email: null,
    expires_at: null,
  });
  vi.mocked(startGoogleDriveOAuth).mockReturnValue(new Promise(() => undefined));
  render();
  expect(await screen.findByText("Google Drive não conectado")).not.toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Conectar Google Drive" }));
  await waitFor(() => expect(startGoogleDriveOAuth).toHaveBeenCalledTimes(1));
  expect(
    (screen.getByRole("button", { name: "Conectar Google Drive" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
});

test("bloqueia a emissão até todos os eventos terem pasta", async () => {
  render();
  await reachDestination();
  expect(
    (screen.getByRole("button", { name: /Confirmar emissão de 1/i }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  expect(
    screen.getByText(
      "Selecione uma pasta do Google Drive para todos os eventos antes de emitir os certificados.",
    ),
  ).not.toBeNull();
});

test("valida pastas distintas para múltiplos eventos e permite trocar antes da emissão", async () => {
  vi.mocked(validateSpreadsheet).mockResolvedValue({
    ...PREVIEW,
    total: 2,
    valid_count: 2,
    events: [
      { key: "Semana", label: "Semana", count: 1 },
      { key: "", label: "Certificados sem evento", count: 1 },
    ],
  });
  vi.mocked(pickGoogleDriveFolder)
    .mockResolvedValueOnce({ id: "folder-semana-0001", name: "Semana 2026" })
    .mockResolvedValueOnce({ id: "folder-sem-evento-02", name: "Sem evento" })
    .mockResolvedValueOnce({ id: "folder-semana-0003", name: "Semana revisada" });
  vi.mocked(selectGoogleDriveFolder)
    .mockResolvedValueOnce({ folder_name: "Semana 2026", ready: true })
    .mockResolvedValueOnce({ folder_name: "Sem evento", ready: true })
    .mockResolvedValueOnce({ folder_name: "Semana revisada", ready: true });
  render();
  await reachDestination();

  fireEvent.click(
    (await screen.findAllByRole("button", { name: "Selecionar pasta no Google Drive" }))[0],
  );
  await screen.findByText("Semana 2026");
  fireEvent.click(screen.getByRole("button", { name: "Selecionar pasta no Google Drive" }));
  await screen.findByText("Sem evento");
  expect(
    (screen.getByRole("button", { name: /Confirmar emissão de 2/i }) as HTMLButtonElement)
      .disabled,
  ).toBe(false);

  fireEvent.click(screen.getAllByRole("button", { name: "Trocar pasta" })[0]);
  await screen.findByText("Semana revisada");
  expect(selectGoogleDriveFolder).toHaveBeenLastCalledWith("folder-semana-0003", "Semana");
});

test("apresenta erro compreensível quando o Picker falha", async () => {
  vi.mocked(pickGoogleDriveFolder).mockRejectedValue(new Error("picker indisponível"));
  render();
  await reachDestination();
  fireEvent.click(
    await screen.findByRole("button", { name: "Selecionar pasta no Google Drive" }),
  );
  expect(
    await screen.findByText("Não foi possível validar a pasta selecionada."),
  ).not.toBeNull();
});
