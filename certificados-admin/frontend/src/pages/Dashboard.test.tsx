import { screen, within } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import Dashboard from "./Dashboard";
import { renderWithProviders } from "../test/renderWithProviders";
import { getDashboardStats, getRecentCertificates } from "../services/api";

vi.mock("../services/api", () => ({
  getDashboardStats: vi.fn(),
  getRecentCertificates: vi.fn(),
  classifyError: () => "server",
  getApiErrorMessage: (_error: unknown, fallback: string) => fallback,
}));

const ordinary = {
  unique_code: "CERT-2026-ACTIVE",
  participant_name: "Ana Ativa",
  event_name: "Semana Acadêmica",
  certificate_type: "speaker",
  certificate_type_label: "Palestrante",
  authors: [],
  status: "ativo",
  download_available: true,
  integrity_status: "verified",
  integrity_blocked: false,
};
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
const mostra = {
  ...ordinary,
  unique_code: "CERT-2026-MOSTRA8",
  participant_name: AUTHORS[0],
  event_name: "Mostra 2026",
  certificate_type: "scientific_initiation",
  certificate_type_label: "Mostra de Iniciação Científica",
  work_title: "Robô seguidor de linha",
  authors: AUTHORS,
};

beforeEach(() => {
  vi.mocked(getDashboardStats).mockResolvedValue({
    total: 2,
    active: 2,
    revoked: 0,
    failed: 0,
    pending: 0,
    recent: 2,
    recent_days: 30,
    integrity_blocked: 0,
    active_without_file: 0,
  });
  vi.mocked(getRecentCertificates).mockResolvedValue([ordinary, mostra]);
});

test("emissões recentes mostram o trabalho e os autores da Mostra, e o titular nos comuns", async () => {
  renderWithProviders(<Dashboard />);
  const table = await screen.findByRole("table", {
    name: "Últimos certificados emitidos, do mais recente para o mais antigo",
  });
  await within(table).findByText("Robô seguidor de linha");

  expect(within(table).getByRole("columnheader", { name: "Participante / Trabalho" })).not.toBeNull();
  const [first, second] = within(table).getAllByRole("rowheader");
  expect(first.textContent).toBe("Ana Ativa");
  expect(second.textContent).toContain("Robô seguidor de linha");
  expect(second.textContent).toContain(`Autores: ${AUTHORS.slice(0, 3).join(", ")} +5`);
  expect(
    within(second).getByRole("button", { name: "+5 autores; mostrar todos" }).getAttribute("title"),
  ).toBe(AUTHORS.join(", "));
});
