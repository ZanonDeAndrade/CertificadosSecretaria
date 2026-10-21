/**
 * Route-level guard behaviour, exercised through the real router.
 *
 * These cover what the tab-based version could not have: a URL that maps to a
 * screen, and a guard that refuses one screen without breaking the rest.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test, vi, beforeEach } from "vitest";
import App from "../App";

const getMe = vi.fn();

vi.mock("../services/api", () => ({
  SESSION_EXPIRED_EVENT: "certificados:session-expired",
  API_BASE_URL: "http://localhost:8000",
  getMe: (...args: unknown[]) => getMe(...args),
  getPublicInstitutionSettings: vi.fn().mockResolvedValue({ institution_name: "Instituição Teste", public_url: "" }),
  logout: vi.fn().mockResolvedValue(undefined),
  login: vi.fn(),
  validateSpreadsheet: vi.fn(),
  validateCertificate: vi.fn(),
  listCertificates: vi
    .fn()
    .mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 }),
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

vi.mock("../pages/TemplateEditor", () => ({
  default: () => <div>Editor de template</div>,
}));

function renderAt(route: string) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <App />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  getMe.mockResolvedValue({
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
  });
});

test("a raiz redireciona para o painel", async () => {
  renderAt("/");
  expect(
    await screen.findByRole("heading", { level: 1, name: /Bom trabalho/ }),
  ).toBeTruthy();
});

test("um link direto abre a tela correspondente", async () => {
  renderAt("/auditoria");
  expect(
    await screen.findByRole("heading", { level: 1, name: "Auditoria" }),
  ).toBeTruthy();
});

test("endereço desconhecido cai no 404 do sistema, com navegação intacta", async () => {
  renderAt("/rota-que-nao-existe");
  expect(
    await screen.findByRole("heading", { level: 1, name: "Página não encontrada" }),
  ).toBeTruthy();
  expect(screen.getAllByRole("navigation").length).toBeGreaterThan(0);
});

test("sessão ausente leva à tela de entrada", async () => {
  getMe.mockRejectedValue(new Error("401"));
  renderAt("/historico");
  expect(
    await screen.findByRole("heading", { name: "Entrar no sistema" }),
  ).toBeTruthy();
});

test("auditor recebe explicação ao abrir uma tela restrita", async () => {
  getMe.mockResolvedValue({ id: 9, name: "Auditoria", username: "auditoria.interna", role: "auditor", permissions: ["certificates.read", "audit.read"], must_change_password: false });
  renderAt("/emitir");
  expect(
    await screen.findByRole("heading", {
      level: 1,
      name: "Sem permissão para esta tela",
    }),
  ).toBeTruthy();
  // The explanation names the user and profile so they know what to ask for.
  // Scoped to the message itself — the username also appears in the topbar.
  const explanation = screen.getByText(/Você está conectado como/);
  expect(explanation.textContent).toContain("auditoria.interna");
  expect(explanation.textContent).toContain("Auditoria");
});

test("auditor continua navegando normalmente nas telas permitidas", async () => {
  getMe.mockResolvedValue({ id: 9, name: "Auditoria", username: "auditoria.interna", role: "auditor", permissions: ["certificates.read", "audit.read"], must_change_password: false });
  renderAt("/historico");
  expect(
    await screen.findByRole("heading", { level: 1, name: "Histórico de certificados" }),
  ).toBeTruthy();
});

test("o menu lateral só lista o que o papel permite", async () => {
  getMe.mockResolvedValue({ id: 9, name: "Auditoria", username: "auditoria.interna", role: "auditor", permissions: ["certificates.read", "audit.read"], must_change_password: false });
  renderAt("/historico");
  await screen.findByRole("heading", { level: 1, name: "Histórico de certificados" });

  await waitFor(() => {
    expect(screen.queryAllByRole("link", { name: "Emitir certificados" })).toHaveLength(0);
    expect(screen.queryAllByRole("link", { name: "Usuários" })).toHaveLength(0);
  });
  expect(screen.getAllByRole("link", { name: "Histórico" }).length).toBeGreaterThan(0);
});
