import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import Usuarios from "./Usuarios";
import { renderWithProviders } from "../test/renderWithProviders";
import {
  createAdminUser,
  listAdminUsers,
  resetAdminUserPassword,
} from "../services/api";

vi.mock("../services/api", () => ({
  listAdminUsers: vi.fn(),
  createAdminUser: vi.fn(),
  updateAdminUser: vi.fn(),
  setAdminUserActive: vi.fn(),
  resetAdminUserPassword: vi.fn(),
  revokeAdminUserSessions: vi.fn(),
  classifyError: () => "server",
  getApiErrorMessage: (error: unknown, fallback: string) =>
    error instanceof Error ? error.message : fallback,
}));

const SELF = {
  id: 1,
  name: "Administrador",
  username: "secretaria",
  role: "admin",
  is_active: true,
  must_change_password: false,
  password_changed_at: "2026-06-01T10:00:00Z",
  created_at: "2026-01-01T10:00:00Z",
};
const OPERATOR = {
  ...SELF,
  id: 2,
  name: "Marina Oliveira",
  username: "m.oliveira",
  role: "secretaria",
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listAdminUsers).mockResolvedValue({ items: [SELF, OPERATOR], total: 2 });
  vi.mocked(createAdminUser).mockImplementation(async (input) => ({
    ...OPERATOR,
    id: 3,
    name: input.name,
    username: input.username,
    role: input.role,
    must_change_password: true,
  }));
  vi.mocked(resetAdminUserPassword).mockResolvedValue({
    user: { ...OPERATOR, must_change_password: true },
    sessions_revoked: 2,
  });
});

test("cria usuário com perfil explícito e nunca reexibe a senha temporária", async () => {
  const user = userEvent.setup();
  renderWithProviders(<Usuarios />);
  await screen.findByText("Marina Oliveira");

  const selfRow = screen.getByText(/secretaria · você/).closest("tr");
  expect(selfRow).not.toBeNull();
  expect(
    (within(selfRow as HTMLElement).getByRole("button", {
      name: "Inativar",
    }) as HTMLButtonElement).disabled,
  ).toBe(true);
  expect(
    (within(selfRow as HTMLElement).getByRole("button", {
      name: "Redefinir senha",
    }) as HTMLButtonElement).disabled,
  ).toBe(true);

  await user.click(screen.getAllByRole("button", { name: "Criar usuário" })[0]);
  const dialog = screen.getByRole("dialog", { name: "Criar usuário" });
  await user.type(within(dialog).getByLabelText(/^Nome/), "Auditora Nova");
  await user.type(within(dialog).getByLabelText(/^Login/), "auditora.nova");
  await user.selectOptions(within(dialog).getByLabelText(/^Perfil/), "auditor");
  await user.type(
    within(dialog).getByLabelText(/^Senha temporária/),
    "Temporaria-Teste-2026!",
  );
  await user.click(within(dialog).getByRole("button", { name: "Criar usuário" }));

  await waitFor(() =>
    expect(createAdminUser).toHaveBeenCalledWith({
      name: "Auditora Nova",
      username: "auditora.nova",
      role: "auditor",
      temporary_password: "Temporaria-Teste-2026!",
    }),
  );
  expect(await screen.findByText(/deverá trocar a senha temporária/)).not.toBeNull();
  expect(screen.queryByDisplayValue("Temporaria-Teste-2026!")).toBeNull();
});

test("redefinição informa revogação e marca a próxima troca como obrigatória", async () => {
  const user = userEvent.setup();
  renderWithProviders(<Usuarios />);
  const row = (await screen.findByText("Marina Oliveira")).closest("tr");
  await user.click(within(row as HTMLElement).getByRole("button", { name: "Redefinir senha" }));

  const dialog = screen.getByRole("dialog", { name: "Redefinir senha" });
  await user.type(
    within(dialog).getByLabelText(/^Nova senha temporária/),
    "Redefinida-Teste-2026!",
  );
  await user.click(within(dialog).getByRole("button", { name: "Redefinir senha" }));

  expect(resetAdminUserPassword).toHaveBeenCalledWith(2, "Redefinida-Teste-2026!");
  expect(await screen.findByText(/2 sessão\(ões\) encerrada\(s\)/)).not.toBeNull();
  expect(screen.queryByDisplayValue("Redefinida-Teste-2026!")).toBeNull();
});
