import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import App from "./App";

vi.mock("./pages/TemplateEditor", () => ({
  default: () => <div>Editor carregado sob demanda</div>,
}));

vi.mock("./services/api", () => ({
  SESSION_EXPIRED_EVENT: "certificados:session-expired",
  API_BASE_URL: "http://localhost:8000",
  getMe: vi.fn().mockResolvedValue({ id: 1, username: "secretaria", role: "admin" }),
  logout: vi.fn().mockResolvedValue(undefined),
  login: vi.fn(),
  validateSpreadsheet: vi.fn(),
  generateCertificatesFromSpreadsheet: vi.fn(),
  validateCertificate: vi.fn(),
  listCertificates: vi.fn(),
  revokeCertificate: vi.fn(),
  downloadCertificatesZip: vi.fn(),
  downloadCertificateFile: vi.fn(),
  getApiErrorMessage: (_error: unknown, fallback: string) => fallback,
}));

test("carrega editor sob demanda e encerra a interface ao expirar sessão", async () => {
  const user = userEvent.setup();
  render(<App />);
  await screen.findByText("secretaria");

  await user.click(screen.getByRole("tab", { name: "Template global" }));
  expect(await screen.findByText("Editor carregado sob demanda")).not.toBeNull();

  window.dispatchEvent(
    new CustomEvent("certificados:session-expired", {
      detail: "Sessão revogada pelo servidor.",
    }),
  );
  await waitFor(() => expect(screen.getByText("Sessão revogada pelo servidor.")).not.toBeNull());
  expect(screen.getByRole("heading", { name: "Entrar" })).not.toBeNull();
});
