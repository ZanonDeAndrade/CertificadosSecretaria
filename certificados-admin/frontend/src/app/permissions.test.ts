/**
 * The permission matrix is the contract the navigation and the route guards
 * both read, so it gets tested directly — a mistake here silently shows an
 * operator a screen the backend will refuse, or hides one they need.
 */
import { describe, expect, test } from "vitest";
import { can, isKnownRole, roleLabel, Role } from "./permissions";
import { NAV_ITEMS } from "./navigation";
import { TEST_PERMISSIONS } from "../test/renderWithProviders";

describe("matriz de permissões", () => {
  test("admin tem acesso a tudo", () => {
    for (const item of NAV_ITEMS) {
      if (!item.permission) continue;
      expect(can(TEST_PERMISSIONS.admin, item.permission), item.label).toBe(true);
    }
  });

  test("secretaria emite e revoga, mas não gerencia acessos nem template", () => {
    expect(can(TEST_PERMISSIONS.secretaria, "certificates.issue")).toBe(true);
    expect(can(TEST_PERMISSIONS.secretaria, "certificates.revoke")).toBe(true);
    expect(can(TEST_PERMISSIONS.secretaria, "certificates.reissue")).toBe(true);
    expect(can(TEST_PERMISSIONS.secretaria, "certificates.download")).toBe(true);
    expect(can(TEST_PERMISSIONS.secretaria, "templates.read")).toBe(false);
    expect(can(TEST_PERMISSIONS.secretaria, "templates.manage")).toBe(false);
    expect(can(TEST_PERMISSIONS.secretaria, "users.manage")).toBe(false);
  });

  test("auditor é somente leitura", () => {
    expect(can(TEST_PERMISSIONS.auditor, "certificates.read")).toBe(true);
    expect(can(TEST_PERMISSIONS.auditor, "audit.read")).toBe(true);
    expect(can(TEST_PERMISSIONS.auditor, "dashboard.read")).toBe(false);
    expect(can(TEST_PERMISSIONS.auditor, "templates.read")).toBe(false);
    expect(can(TEST_PERMISSIONS.auditor, "certificates.issue")).toBe(false);
    expect(can(TEST_PERMISSIONS.auditor, "certificates.revoke")).toBe(false);
    expect(can(TEST_PERMISSIONS.auditor, "certificates.reissue")).toBe(false);
    expect(can(TEST_PERMISSIONS.auditor, "certificates.download")).toBe(false);
    expect(can(TEST_PERMISSIONS.auditor, "templates.manage")).toBe(false);
    expect(can(TEST_PERMISSIONS.auditor, "users.manage")).toBe(false);
  });

  test("papel desconhecido ou ausente não recebe nada (falha fechada)", () => {
    for (const permission of [
      "certificates.read",
      "certificates.issue",
      "users.manage",
      "audit.read",
    ] as const) {
      expect(can(undefined, permission)).toBe(false);
      expect(can([], permission)).toBe(false);
    }
  });

  test("papéis conhecidos são exatamente os do banco", () => {
    for (const role of ["admin", "secretaria", "auditor"] as Role[]) {
      expect(isKnownRole(role)).toBe(true);
      expect(roleLabel(role)).not.toBe("Perfil não reconhecido");
    }
    expect(isKnownRole("root")).toBe(false);
    expect(roleLabel("root")).toBe("Perfil não reconhecido");
  });
});

describe("navegação", () => {
  test("todo item de menu aponta para uma rota absoluta", () => {
    for (const item of NAV_ITEMS) {
      expect(item.to.startsWith("/"), item.label).toBe(true);
    }
  });

  test("não há rotas duplicadas", () => {
    const routes = NAV_ITEMS.map((item) => item.to);
    expect(new Set(routes).size).toBe(routes.length);
  });

  test("cada papel enxerga um subconjunto coerente do menu", () => {
    const visible = (role: Role) =>
      NAV_ITEMS.filter(
        (item) => !item.permission || can(TEST_PERMISSIONS[role], item.permission),
      ).map(
        (item) => item.to,
      );

    const auditor = visible("auditor");
    const secretaria = visible("secretaria");
    const admin = visible("admin");

    expect(auditor.length).toBeLessThan(secretaria.length);
    expect(secretaria.length).toBeLessThan(admin.length);
    expect(secretaria.every((route) => admin.includes(route))).toBe(true);
    expect(auditor).toContain("/auditoria");
    expect(auditor).toContain("/historico");
    expect(auditor).not.toContain("/painel");
    expect(auditor).not.toContain("/emitir");
  });

  test("telas sem permissão explícita são abertas a qualquer sessão", () => {
    const open = NAV_ITEMS.filter((item) => !item.permission).map((item) => item.to);
    expect(open).toContain("/validar");
  });
});
