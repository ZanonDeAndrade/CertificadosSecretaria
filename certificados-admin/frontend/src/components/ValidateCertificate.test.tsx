import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import ValidateCertificate from "./ValidateCertificate";
import { renderWithProviders } from "../test/renderWithProviders";
import { validateCertificate } from "../services/api";

vi.mock("../services/api", () => ({
  validateCertificate: vi.fn(),
  classifyError: () => "server",
}));

beforeEach(() => {
  vi.mocked(validateCertificate).mockResolvedValue({
    valid: true,
    name: "João Sintético",
    event: "Semana Acadêmica",
    issued_at: "15 de agosto de 2026",
    certificate_type: "speaker",
    certificate_type_label: "Palestrante",
  });
});

test("mostra o tipo oficial retornado pela consulta pública", async () => {
  const user = userEvent.setup();
  renderWithProviders(<ValidateCertificate />);
  await user.type(screen.getByRole("textbox", { name: /Código do certificado/i }), "CERT-2026-ABC123");
  await user.click(screen.getByRole("button", { name: "Validar" }));

  expect(await screen.findByText("Palestrante")).not.toBeNull();
  expect(validateCertificate).toHaveBeenCalledWith("CERT-2026-ABC123");
});
