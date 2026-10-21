import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import PasswordChangeForm from "./PasswordChangeForm";
import { changeOwnPassword } from "../services/api";

vi.mock("../services/api", () => ({
  changeOwnPassword: vi.fn(),
  getApiErrorMessage: (error: unknown, fallback: string) =>
    error instanceof Error ? error.message : fallback,
}));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(changeOwnPassword).mockResolvedValue({ ok: true, sessions_revoked: 2 });
});

test("exige senha atual, confirmação coincidente e encerra outras sessões", async () => {
  const user = userEvent.setup();
  const changed = vi.fn();
  render(<PasswordChangeForm onChanged={changed} />);

  const submit = screen.getByRole("button", { name: "Alterar senha" }) as HTMLButtonElement;
  expect(submit.disabled).toBe(true);

  await user.type(screen.getByLabelText(/^Senha atual/), "Atual-Forte-2026!");
  await user.type(screen.getByLabelText(/^Nova senha/), "Nova-Forte-2026!!");
  await user.type(screen.getByLabelText(/^Confirmar nova senha/), "Diferente-2026!!");
  expect(screen.getByText("As senhas novas não coincidem.")).not.toBeNull();
  expect(submit.disabled).toBe(true);

  await user.clear(screen.getByLabelText(/^Confirmar nova senha/));
  await user.type(screen.getByLabelText(/^Confirmar nova senha/), "Nova-Forte-2026!!");
  await user.click(submit);

  await waitFor(() =>
    expect(changeOwnPassword).toHaveBeenCalledWith(
      "Atual-Forte-2026!",
      "Nova-Forte-2026!!",
    ),
  );
  expect(changed).toHaveBeenCalledWith(2);
  expect(await screen.findByText(/2 outra\(s\) sessão\(ões\) foram encerradas/)).not.toBeNull();
  expect((screen.getByLabelText(/^Senha atual/) as HTMLInputElement).value).toBe("");
});

test("preserva a mensagem segura do backend e devolve foco à senha atual", async () => {
  const user = userEvent.setup();
  vi.mocked(changeOwnPassword).mockRejectedValueOnce(
    new Error("A senha atual está incorreta."),
  );
  render(<PasswordChangeForm />);

  const current = screen.getByLabelText(/^Senha atual/);
  await user.type(current, "Atual-Incorreta-2026!");
  await user.type(screen.getByLabelText(/^Nova senha/), "Nova-Forte-2026!!");
  await user.type(screen.getByLabelText(/^Confirmar nova senha/), "Nova-Forte-2026!!");
  await user.click(screen.getByRole("button", { name: "Alterar senha" }));

  expect(await screen.findByText("A senha atual está incorreta.")).not.toBeNull();
  await waitFor(() => expect(document.activeElement).toBe(current));
});
