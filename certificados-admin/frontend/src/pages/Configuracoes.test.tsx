import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import Configuracoes from "./Configuracoes";
import { renderWithProviders } from "../test/renderWithProviders";
import {
  getInstitutionalSettings,
  updateInstitutionalSettings,
} from "../services/api";

vi.mock("../services/api", () => ({
  getInstitutionalSettings: vi.fn(),
  updateInstitutionalSettings: vi.fn(),
  classifyError: () => "server",
  getApiErrorMessage: (error: unknown, fallback: string) =>
    error instanceof Error ? error.message : fallback,
}));

const SETTINGS = {
  id: 1,
  institution_name: "Instituição Original",
  issue_location: "São Paulo",
  signatory_name: "Helena Martins",
  signatory_title: "Diretora Acadêmica",
  public_url: "https://certificados.example.test",
  retention_days: 730,
  max_batch_rows: 2000,
  max_upload_mb: 10,
  secretaria_can_revoke: true,
  secretaria_can_reissue: true,
  updated_at: "2026-06-01T10:00:00Z",
  updated_by: 1,
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getInstitutionalSettings).mockResolvedValue(SETTINGS);
  vi.mocked(updateInstitutionalSettings).mockImplementation(async (input) => ({
    ...SETTINGS,
    ...input,
  }));
});

test("admin altera dados institucionais e política operacional tipada", async () => {
  const user = userEvent.setup();
  renderWithProviders(<Configuracoes />);

  const name = await screen.findByLabelText(/^Nome da instituição/);
  await waitFor(() =>
    expect((name as HTMLInputElement).value).toBe("Instituição Original"),
  );
  await user.clear(name);
  await user.type(name, "Instituição Atualizada");
  await user.click(screen.getByLabelText("Pode revogar certificados"));
  await user.click(screen.getByRole("button", { name: "Salvar configurações" }));

  await waitFor(() =>
    expect(updateInstitutionalSettings).toHaveBeenCalledWith(
      expect.objectContaining({
        institution_name: "Instituição Atualizada",
        secretaria_can_revoke: false,
        secretaria_can_reissue: true,
        max_batch_rows: 2000,
      }),
    ),
  );
  expect(await screen.findByText(/atualizadas e registradas na auditoria/)).not.toBeNull();
  expect(screen.getByText(/Segredos, credenciais, tokens e chaves não pertencem/)).not.toBeNull();
});

test("perfil sem permissão de escrita recebe formulário somente leitura", async () => {
  renderWithProviders(<Configuracoes />, { role: "auditor" });
  const name = await screen.findByLabelText(/^Nome da instituição/);
  expect((name as HTMLInputElement).disabled).toBe(true);
  expect(screen.queryByRole("button", { name: "Salvar configurações" })).toBeNull();
  expect(screen.getByText(/disponível somente para leitura/)).not.toBeNull();
});

test("o local de emissão é apresentado como a cidade que sai no certificado", async () => {
  renderWithProviders(<Configuracoes />, { role: "admin" });

  const field = (await screen.findByLabelText(
    /Cidade \(local de emissão\)/,
  )) as HTMLInputElement;
  await waitFor(() => expect(field.value).toBe(SETTINGS.issue_location));
  expect(screen.getByText(/Sai como “Cidade, data\.” nos certificados/)).toBeTruthy();
});
