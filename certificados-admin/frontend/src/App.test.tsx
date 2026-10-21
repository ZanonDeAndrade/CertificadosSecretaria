/**
 * App-level behaviour.
 *
 * This file previously drove the tab bar (`role="tab"`). The tabs were replaced
 * by real routes and a sidebar, so the navigation step is expressed against the
 * new structure — but both original assertions are kept intact: the template
 * editor is still loaded lazily, and a server-revoked session still tears the
 * interface down and returns the operator to the sign-in screen.
 */
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import App from "./App";

vi.mock("./pages/TemplateEditor", () => ({
  default: () => <div>Editor carregado sob demanda</div>,
}));

vi.mock("./services/api", () => ({
  SESSION_EXPIRED_EVENT: "certificados:session-expired",
  API_BASE_URL: "http://localhost:8000",
  getMe: vi.fn().mockResolvedValue({
    id: 1,
    name: "Secretaria",
    username: "secretaria",
    role: "admin",
    permissions: [
      "dashboard.read", "certificates.read", "certificates.issue",
      "certificates.revoke", "certificates.reissue", "certificates.download",
      "templates.read", "templates.manage", "users.manage", "sessions.manage",
      "audit.read", "settings.read", "settings.manage",
    ],
    must_change_password: false,
  }),
  getPublicInstitutionSettings: vi.fn().mockResolvedValue({ institution_name: "Instituição Teste", public_url: "" }),
  logout: vi.fn().mockResolvedValue(undefined),
  login: vi.fn(),
  validateSpreadsheet: vi.fn(),
  validateCertificate: vi.fn(),
  listCertificates: vi.fn().mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 }),
  revokeCertificate: vi.fn(),
  downloadCertificatesZip: vi.fn(),
  downloadCertificateFile: vi.fn(),
  getDashboardStats: vi.fn().mockResolvedValue({
    total: 0,
    active: 0,
    revoked: 0,
    failed: 0,
    pending: 0,
    recent: 0,
    recent_days: 30,
    integrity_blocked: 0,
    active_without_file: 0,
  }),
  getRecentCertificates: vi.fn().mockResolvedValue([]),
  listAdminUsers: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  updateAdminUser: vi.fn(),
  listAuditLog: vi.fn().mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 }),
  classifyError: () => "server",
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  getApiErrorMessage: (_error: unknown, fallback: string) => fallback,
}));

function renderApp(route = "/painel") {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <App />
    </MemoryRouter>,
  );
}

test("carrega editor sob demanda e encerra a interface ao expirar sessão", async () => {
  const user = userEvent.setup();
  renderApp();
  await screen.findAllByText("secretaria");
  expect(screen.getAllByText("Certificados Faculdade AMF").length).toBeGreaterThan(0);
  expect(document.querySelector('img[src="/logo-amf.jpg"]')).not.toBeNull();
  expect(document.title).toBe("Painel · Certificados Faculdade AMF");

  // Navigate through the sidebar rather than the old tab bar.
  const editorLink = screen
    .getAllByRole("link", { name: /Template do certificado/ })
    .at(0)!;
  await user.click(editorLink);
  expect(await screen.findByText("Editor carregado sob demanda")).not.toBeNull();

  act(() => {
    window.dispatchEvent(
      new CustomEvent("certificados:session-expired", {
        detail: "Sessão revogada pelo servidor.",
      }),
    );
  });
  await waitFor(() =>
    expect(screen.getByText("Sessão revogada pelo servidor.")).not.toBeNull(),
  );
  expect(screen.getByRole("heading", { name: "Entrar no sistema" })).not.toBeNull();
});
