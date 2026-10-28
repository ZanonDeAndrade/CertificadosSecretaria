import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, vi } from "vitest";
import Historico from "./Historico";
import { renderWithProviders } from "../test/renderWithProviders";
import {
  downloadCertificateFile,
  downloadCertificatesZip,
  getCertificate,
  listCertificates,
  reissueCertificate,
  revokeCertificate,
} from "../services/api";

vi.mock("../services/api", () => ({
  listCertificates: vi.fn(),
  revokeCertificate: vi.fn(),
  downloadCertificatesZip: vi.fn(),
  downloadCertificateFile: vi.fn(),
  getCertificate: vi.fn(),
  reissueCertificate: vi.fn(),
  classifyError: () => "server",
  getApiErrorMessage: (error: unknown, fallback: string) =>
    error instanceof Error ? error.message : fallback,
}));

/** The screen now lives inside the app shell's router + auth providers. */
const render = (role = "admin") => renderWithProviders(<Historico />, { role });

const active = {
  unique_code: "CERT-2026-ACTIVE",
  participant_name: "Ana Ativa",
  course_name: "Direito",
  event_name: "Evento",
  certificate_type: "speaker",
  certificate_type_label: "Palestrante",
  issue_date: "10/06/2026",
  status: "ativo",
  download_available: true,
  integrity_status: "verified",
  integrity_blocked: false,
};
const revoked = {
  ...active,
  unique_code: "CERT-2026-REVOKED",
  participant_name: "Rita Revogada",
  status: "revogado",
  download_available: false,
};
const unavailable = {
  ...active,
  unique_code: "CERT-2026-MISSING",
  participant_name: "Ivo Indisponível",
  download_available: false,
};

/* Per-work (Mostra) certificates: one per work, valid for every author. */
const AUTHORS = [
  "Pessoa Exemplo Alfa",
  "Pessoa Exemplo Beta",
  "Pessoa Exemplo Gama",
  "Pessoa Exemplo Delta",
  "Pessoa Exemplo Épsilon",
  "Pessoa Exemplo Zeta",
  "Pessoa Exemplo Eta",
  "Pessoa Exemplo Teta",
];
const mostraWork = (code: string, work_title: string, count: number) => ({
  ...active,
  unique_code: code,
  participant_name: AUTHORS[0],
  certificate_type: "scientific_initiation",
  certificate_type_label: "Mostra de Iniciação Científica",
  work_title,
  team_name: "Equipe Verde",
  authors: AUTHORS.slice(0, count),
});
const mostra1 = mostraWork("CERT-2026-MOSTRA1", "Compostagem doméstica", 1);
const mostra3 = mostraWork("CERT-2026-MOSTRA3", "Horta vertical automatizada", 3);
const mostra8 = mostraWork("CERT-2026-MOSTRA8", "Robô seguidor de linha", 8);

const listMostra = () =>
  vi.mocked(listCertificates).mockResolvedValue({
    items: [active, mostra1, mostra3, mostra8],
    total: 4,
    limit: 20,
    offset: 0,
  });

/** The row of the table whose row header starts with `text`. */
const rowOf = (text: string) => {
  const row = screen.getByRole("rowheader", { name: new RegExp(`^${text}`) }).closest("tr");
  if (!row) throw new Error(`row not found: ${text}`);
  return row;
};

beforeEach(() => {
  vi.mocked(listCertificates).mockResolvedValue({
    items: [active, revoked, unavailable],
    total: 3,
    limit: 20,
    offset: 0,
  });
  vi.mocked(revokeCertificate).mockResolvedValue({ ...active, status: "revogado" });
  vi.mocked(downloadCertificatesZip).mockImplementation(async (_codes, progress) => {
    progress?.(50);
    return { blob: new Blob(["zip"]), skippedCodes: ["CERT-2026-MISSING"] };
  });
});

test("seleciona apenas disponíveis e informa download ZIP parcial", async () => {
  const user = userEvent.setup();
  render();
  await screen.findByText("Ana Ativa");
  expect(screen.getAllByText("Palestrante").length).toBeGreaterThan(0);

  expect((screen.getByRole("checkbox", { name: /Rita Revogada/ }) as HTMLInputElement).disabled).toBe(true);
  expect((screen.getByRole("checkbox", { name: /Ivo Indisponível/ }) as HTMLInputElement).disabled).toBe(true);
  await user.click(screen.getByRole("button", { name: "Selecionar página" }));
  await user.click(screen.getByRole("button", { name: "Baixar ZIP (1)" }));

  await waitFor(() => expect(downloadCertificatesZip).toHaveBeenCalledWith([active.unique_code], expect.any(Function)));
  expect(await screen.findByText(/ZIP gerado parcialmente/)).not.toBeNull();
});

test("salva o certificado com o nome sugerido pela API", async () => {
  const user = userEvent.setup();
  const filename = "Ana Ativa - Evento de Inovação - CERT-2026-ACTIVE.pdf";
  vi.mocked(downloadCertificateFile).mockResolvedValue({ blob: new Blob(["pdf"]), filename });
  const saved: string[] = [];
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    saved.push(this.download);
  });
  render();
  await screen.findByText("Ana Ativa");
  await user.click(screen.getAllByRole("button", { name: "Baixar certificado de Ana Ativa" })[0]);

  await waitFor(() => expect(saved).toEqual([filename]));
  expect(downloadCertificateFile).toHaveBeenCalledWith(active.unique_code);
});

test("exige motivo e preserva erro específico ao revogar", async () => {
  const user = userEvent.setup();
  vi.mocked(revokeCertificate).mockRejectedValueOnce(new Error("Conflito específico do backend."));
  render();
  await screen.findByText("Ana Ativa");
  await user.click(screen.getAllByRole("button", { name: "Revogar" })[0]);

  const reason = screen.getByRole("textbox", { name: "Motivo" });
  expect(document.activeElement).toBe(reason);
  const confirm = screen.getByRole("button", { name: "Confirmar revogação" }) as HTMLButtonElement;
  expect(confirm.disabled).toBe(true);
  await user.type(reason, "erro de emissão");
  expect(confirm.disabled).toBe(false);
  await user.click(confirm);
  expect(await screen.findByText("Conflito específico do backend.")).not.toBeNull();
});

test("filtra pelo tipo controlado e envia o identificador interno à API", async () => {
  const user = userEvent.setup();
  render();
  await screen.findByText("Ana Ativa");
  await user.selectOptions(
    screen.getByRole("combobox", { name: "Tipo do certificado" }),
    "speaker",
  );
  await user.click(screen.getByRole("button", { name: "Buscar" }));

  await waitFor(() =>
    expect(listCertificates).toHaveBeenLastCalledWith(
      expect.objectContaining({ certificate_type: "speaker" }),
    ),
  );
});

test("Mostra: a coluna mostra o trabalho e os autores; o comum continua pelo titular", async () => {
  listMostra();
  render();
  await screen.findByText("Robô seguidor de linha");

  expect(screen.getByRole("columnheader", { name: "Participante / Trabalho" })).not.toBeNull();
  expect(screen.getByRole("rowheader", { name: "Ana Ativa" }).textContent).toBe("Ana Ativa");
  expect(screen.getByRole("checkbox", { name: "Selecionar certificado de Ana Ativa" })).not.toBeNull();

  expect(rowOf("Compostagem doméstica").querySelector("th")?.textContent).toBe(
    `Compostagem domésticaAutor: ${AUTHORS[0]}`,
  );
  expect(rowOf("Horta vertical automatizada").querySelector("th")?.textContent).toBe(
    `Horta vertical automatizadaAutores: ${AUTHORS.slice(0, 3).join(", ")}`,
  );

  const eight = rowOf("Robô seguidor de linha");
  expect(eight.querySelector("th")?.textContent).toContain(
    `Autores: ${AUTHORS.slice(0, 3).join(", ")} +5`,
  );
  expect(eight.querySelector("th")?.textContent).not.toContain(AUTHORS[7]);
  const more = within(eight).getByRole("button", { name: "+5 autores; mostrar todos" });
  // Mouse: the native tooltip carries every author.
  expect(more.getAttribute("title")).toBe(AUTHORS.join(", "));
  expect(
    within(eight).getByRole("checkbox", {
      name: "Selecionar certificado do trabalho “Robô seguidor de linha”",
    }),
  ).not.toBeNull();
  expect(
    within(eight).getByRole("button", {
      name: "Baixar certificado do trabalho “Robô seguidor de linha”",
    }),
  ).not.toBeNull();
});

test("Mostra: o detalhe lista trabalho, todos os autores e a equipe", async () => {
  const user = userEvent.setup();
  listMostra();
  vi.mocked(getCertificate).mockResolvedValue(mostra8);
  render();
  await screen.findByText("Robô seguidor de linha");

  await user.click(
    screen.getByRole("button", { name: "Ver detalhes do trabalho “Robô seguidor de linha”" }),
  );
  const dialog = await screen.findByRole("dialog");
  await waitFor(() => expect(getCertificate).toHaveBeenCalledWith(mostra8.unique_code));
  expect(within(dialog).getByText("Trabalho")).not.toBeNull();
  expect(within(dialog).getByText("Equipe Verde")).not.toBeNull();
  expect(within(dialog).queryByText("Participante")).toBeNull();
  expect(within(dialog).getAllByRole("listitem").map((item) => item.textContent)).toEqual(AUTHORS);
});

test("Mostra: revogar e reemitir nomeiam o trabalho e todos os autores", async () => {
  const user = userEvent.setup();
  listMostra();
  vi.mocked(reissueCertificate).mockResolvedValue(mostra8);
  render();
  await screen.findByText("Robô seguidor de linha");

  await user.click(within(rowOf("Robô seguidor de linha")).getByRole("button", { name: "Revogar" }));
  let dialog = await screen.findByRole("dialog");
  expect(dialog.textContent).toContain(
    "O certificado do trabalho Robô seguidor de linha deixará de ser válido",
  );
  expect(dialog.textContent).toContain(`Autores: ${AUTHORS.join(", ")}`);
  await user.click(within(dialog).getByRole("button", { name: "Cancelar" }));

  await user.click(within(rowOf("Robô seguidor de linha")).getByRole("button", { name: "Reemitir" }));
  dialog = await screen.findByRole("dialog");
  expect(dialog.textContent).toContain(
    "Reemitir o certificado do trabalho Robô seguidor de linha, código CERT-2026-MOSTRA8?",
  );
  expect(dialog.textContent).toContain(`Autores: ${AUTHORS.join(", ")}`);
  await user.click(within(dialog).getByRole("button", { name: "Confirmar reemissão" }));
  expect(
    await screen.findByText("Certificado do trabalho “Robô seguidor de linha” reemitido com sucesso."),
  ).not.toBeNull();
});

test("comum: diálogos e mensagem de reemissão continuam pelo titular", async () => {
  const user = userEvent.setup();
  vi.mocked(reissueCertificate).mockResolvedValue(active);
  render();
  await screen.findByText("Ana Ativa");

  await user.click(within(rowOf("Ana Ativa")).getByRole("button", { name: "Reemitir" }));
  const dialog = await screen.findByRole("dialog");
  expect(dialog.textContent).toContain("Reemitir o certificado de Ana Ativa, código CERT-2026-ACTIVE?");
  expect(dialog.textContent).not.toContain("Autor");
  await user.click(within(dialog).getByRole("button", { name: "Confirmar reemissão" }));
  expect(await screen.findByText("Certificado de Ana Ativa reemitido com sucesso.")).not.toBeNull();
});

test("celular: o “+N” expande pelo toque e o detalhe lista todos os autores", async () => {
  const user = userEvent.setup();
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: false,
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));
  try {
    listMostra();
    vi.mocked(getCertificate).mockResolvedValue(mostra8);
    render();
    const title = await screen.findByText("Robô seguidor de linha");
    expect(screen.queryByRole("table")).toBeNull();
    const item = title.closest("li");
    if (!item) throw new Error("list item not found");
    expect(item.textContent).not.toContain(AUTHORS[7]);

    await user.click(within(item).getByRole("button", { name: "+5 autores; mostrar todos" }));
    expect(item.textContent).toContain(`Autores: ${AUTHORS.join(", ")}`);

    await user.click(within(item).getByRole("button", { name: "Detalhes" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getAllByRole("listitem").map((entry) => entry.textContent)).toEqual(
      AUTHORS,
    );
  } finally {
    vi.unstubAllGlobals();
  }
});

test("o filtro de nome avisa que também encontra qualquer autor", async () => {
  render();
  await screen.findByText("Ana Ativa");
  const input = screen.getByRole("textbox", { name: "Nome do participante" });
  const hint = document.getElementById(input.getAttribute("aria-describedby") ?? "");
  expect(hint?.textContent).toBe("A busca por nome também encontra qualquer autor de um trabalho.");
});
