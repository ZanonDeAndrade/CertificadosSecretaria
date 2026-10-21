/**
 * Navigation, real routes and permissions.
 *
 * The tabbed version of this app had one URL, so refreshing always returned to
 * "Emitir" and links could not be shared. These tests exist so that cannot
 * regress: every screen must survive a reload and a direct link.
 */
import { test, expect, Page } from "@playwright/test";

/** Signs in the mock API with a given role for the whole context. */
async function useRole(page: Page, role: string) {
  await page.context().setExtraHTTPHeaders({
    "x-mock-scenario": "default",
    "x-mock-role": role,
  });
}

/**
 * Returns the primary navigation, opening the mobile drawer first when the
 * sidebar is not on screen. Below `lg` the navigation lives in a drawer, so a
 * test that assumes a permanently visible sidebar only passes on desktop.
 */
async function openNav(page: Page) {
  const toggle = page.getByRole("button", { name: "Abrir menu de navegação" });
  if (await toggle.isVisible()) {
    await toggle.click();
    await expect(page.getByRole("dialog", { name: "Menu de navegação" })).toBeVisible();
  }
  return page.getByRole("navigation", { name: "Navegação principal" }).first();
}

test.describe("rotas reais", () => {
  test("cada tela tem URL própria e sobrevive ao refresh", async ({ page }) => {
    await useRole(page, "admin");
    await page.goto("/painel");
    await expect(page.getByRole("heading", { level: 1 })).toContainText(
      "Bom trabalho",
    );
    const mobileMenu = page.getByRole("button", { name: "Abrir menu de navegação" });
    const brand = (await mobileMenu.isVisible())
      ? page.locator("header")
      : page.locator(".on-dark").first();
    await expect(brand.getByText("Certificados Faculdade AMF")).toBeVisible();
    await expect(page).toHaveTitle("Painel · Certificados Faculdade AMF");
    const logo = brand.locator('img[src="/logo-amf.jpg"]');
    await expect(logo).toBeVisible();
    await expect.poll(() => logo.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBe(400);

    // Navigating updates the URL.
    const nav = await openNav(page);
    await nav.getByRole("link", { name: "Histórico" }).first().click();
    await expect(page).toHaveURL(/\/historico$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      "Histórico de certificados",
    );

    // Refresh keeps the same screen — the whole point of real routes.
    await page.reload();
    await expect(page).toHaveURL(/\/historico$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      "Histórico de certificados",
    );
  });

  test("link direto abre a tela correta", async ({ page }) => {
    await useRole(page, "admin");
    await page.goto("/auditoria");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Auditoria");
  });

  test("filtros do histórico ficam na URL e são compartilháveis", async ({ page }) => {
    await useRole(page, "admin");
    await page.goto("/historico");
    await page.getByLabel("Nome do participante").fill("Beatriz");
    await page.getByRole("button", { name: "Buscar" }).click();

    await expect(page).toHaveURL(/name=Beatriz/);

    // A colleague opening that URL sees the same filtered view.
    await page.goto(page.url());
    await expect(page.getByLabel("Nome do participante")).toHaveValue("Beatriz");
  });

  test("endereço inexistente mostra 404 dentro do sistema", async ({ page }) => {
    await useRole(page, "admin");
    await page.goto("/nao-existe");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      "Página não encontrada",
    );
    // Navigation stays available so the user is one click from somewhere real.
    await expect(page.getByRole("link", { name: "Painel" }).first()).toBeVisible();
  });
});

test.describe("permissões", () => {
  test("auditor não vê emissão nem usuários no menu", async ({ page }) => {
    await useRole(page, "auditor");
    await page.goto("/historico");

    const nav = await openNav(page);
    await expect(nav.getByRole("link", { name: "Histórico" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Auditoria" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Emitir certificados" })).toHaveCount(0);
    await expect(nav.getByRole("link", { name: "Usuários" })).toHaveCount(0);
  });

  test("auditor que abre /emitir direto recebe explicação, não erro", async ({ page }) => {
    await useRole(page, "auditor");
    await page.goto("/emitir");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      "Sem permissão para esta tela",
    );
    await expect(page.getByText("Acesso restrito")).toBeVisible();
  });

  test("secretaria vê emissão mas não usuários", async ({ page }) => {
    await useRole(page, "secretaria");
    await page.goto("/painel");
    const nav = await openNav(page);
    await expect(nav.getByRole("link", { name: "Emitir certificados" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Usuários" })).toHaveCount(0);

    await page.goto("/usuarios");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      "Sem permissão para esta tela",
    );
  });

  test("admin vê todas as áreas", async ({ page }) => {
    await useRole(page, "admin");
    await page.goto("/painel");
    const nav = await openNav(page);
    for (const label of [
      "Painel",
      "Emitir certificados",
      "Histórico",
      "Validar certificado",
      "Template do certificado",
      "Usuários",
      "Auditoria",
      "Configurações",
    ]) {
      await expect(nav.getByRole("link", { name: label })).toBeVisible();
    }
  });
});

test.describe("navegação por teclado", () => {
  test("skip link leva ao conteúdo", async ({ page }, testInfo) => {
    // Emulated touch devices have no sequential-focus starting point, so Tab
    // does not move focus there. The skip link is a keyboard affordance and is
    // verified on the desktop project, which is the real keyboard context.
    test.skip(testInfo.project.name !== "desktop", "verificação de teclado");
    await useRole(page, "admin");
    await page.goto("/painel");
    // Wait for the session check to resolve — until it does, the app renders a
    // loading screen with no skip link, and Tab has nothing to reach.
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.keyboard.press("Tab");

    const skip = page.getByRole("link", { name: "Ir para o conteúdo" });
    await expect(skip).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/#conteudo$/);
  });
});
